# -*- coding: utf-8 -*-
"""分镜阶段：分镜表生成分镜面板(图提示词润色) / 分镜图与重生 / 关联资产。"""
import json
import re

from sqlalchemy import select

from backend.toonflow.pipeline import common, submit, session_scope_ctx
from backend.toonflow.core.models import TfAsset, TfImage, TfProject, TfScript, TfStoryboard
from backend.toonflow.core.paths import copy_into_oss


def _assets_text(session, project_id: int) -> str:
    rows = session.scalars(select(TfAsset).where(
        TfAsset.projectId == project_id, TfAsset.assetsId.is_(None))).all()
    return "\n".join(f"[A{r.id}, {r.type}, {r.name}] {r.describe}" for r in rows)


def _script_text(session, script_id: int) -> str:
    script = session.get(TfScript, script_id)
    return (script.scriptData or "") if script else ""


def generate_storyboard_table(project_id: int, script_id: int) -> dict:
    """按剧本+资产生成"拍摄计划/分镜表"（异步；P3 由导演计划 Agent 细化）。"""
    submit(_storyboard_table_job, project_id, script_id)
    return {"queued": 1}


def _storyboard_table_job(project_id: int, script_id: int) -> None:
    with session_scope_ctx() as session:
        project = session.get(TfProject, project_id)
        if project is None:
            return
        assets = _assets_text(session, project_id)
        script_text = _script_text(session, script_id)
        system = common.skill_body("production_execution_storyboard_table.md")

    # 项目级导演约束：题材叙事技法（story_skills/<题材>/driector_skills）+ 导演手册
    narrative = common.story_narrative_body(getattr(project, "storyStyle", "") or "",
                                            "director_storyboard_table_narrative.md")
    director_manual = (getattr(project, "directorManual", "") or "").strip()
    constraints = ""
    if narrative:
        constraints += f"\n\n## 题材叙事技法（导演风格，务必遵循）\n{narrative[:6000]}"
    if director_manual:
        constraints += f"\n\n## 导演手册（用户指定要求）\n{director_manual[:4000]}"

    prompt = (f"项目画风：{project.artStyle or '未设定'}"
              f"｜题材风格：{getattr(project, 'storyStyle', '') or '未设定'}\n\n"
              f"{constraints}\n\n资产清单：\n{assets}\n\n"
              f"剧本：\n{script_text[:30000]}\n\n"
              '请输出分镜表，直接输出 JSON：{"storyboardTable": [{'
              '"videoDesc": "（画面描述、场景、关联资产名称、时长、景别、运镜、角色动作、情绪、光影氛围、台词、音效、关联资产ID）", '
              '"duration": 秒数, "track": "main", "associateAssetsIds": ["A1"], "shouldGenerateImage": true}]}。'
              "videoDesc 必须严格按括号内 12 个字段、顿号分隔。")
    data = common.parse_json(common.llm(prompt, system=system, json_mode=True, project_id=project_id))
    items = data.get("storyboardTable") or []
    if not items:
        raise RuntimeError("分镜表生成结果为空")

    from backend.control_plane.database import session_scope

    with session_scope() as session:
        # 覆盖式重建该项目分镜（重生入口也可调用）
        session.query(TfStoryboard).filter(TfStoryboard.projectId == project_id).delete()
        for i, item in enumerate(items):
            session.add(TfStoryboard(
                projectId=project_id, scriptId=script_id,
                videoDesc=str(item.get("videoDesc") or ""),
                duration=int(item.get("duration") or 4),
                track=str(item.get("track") or "main"),
                assetIds=json.dumps(item.get("associateAssetsIds") or [], ensure_ascii=False),
                shouldGenerateImage=bool(item.get("shouldGenerateImage", True)),
                orderNo=i + 1,
            ))
    print(f"[toonflow:storyboard] table project={project_id} items={len(items)}")


def polish_storyboard_prompts(project_id: int) -> dict:
    """分镜面板：为每个分镜润色生图提示词（异步，画风前缀注入）。"""
    submit(_polish_prompts_job, project_id)
    return {"queued": 1}


def generate_storyboard_table_sync(project_id: int, script_id: int) -> None:
    """同步版分镜表生成（Agent 工具直接调用，阻塞至完成）。"""
    _storyboard_table_job(project_id, script_id)


# --------------------------------------------------------------------------- #
# Agent 产出落库：解析 <storyboardTable> 标签文本（源"面板流式写入"的服务端等价物）
# --------------------------------------------------------------------------- #
_SCENE_RE = re.compile(r"^##\s*场(\d+)[:：]\s*(.+?)(?:\s*[｜|]\s*参演角色[:：].*)?$")
_SEG_RE = re.compile(r"^###\s*片段")
_ASSET_IDS_RE = re.compile(r"\*\*引用资产ID\*\*[:：]\s*\[([^\]]*)\]")
_ROW_SPLIT_RE = re.compile(r"\s*\|\s*")


def persist_storyboard_table_markdown(project_id: int, text: str,
                                      script_id: int | None = None) -> int:
    """把执行层输出的 <storyboardTable> markdown 解析为分镜行并重建入库。

    格式（production_execution_storyboard_table.md「输出格式」）：
        ## 场N：场景名 ｜ 参演角色：…
        ### 片段一（约10s）
        **引用资产ID**：[101, 100]
        | 序号 | 画面描述 | 时长 | 景别 | 运镜 | 台词 | 音效 |
    返回写入的分镜行数；未找到标签/无有效行返回 0（由调用方决定是否告警）。
    """
    import re as _re

    m = _re.search(r"<storyboardTable>([\s\S]*?)</storyboardTable>", text or "")
    body = m.group(1) if m else (text or "")
    rows: list[dict] = []
    track = ""
    seg_asset_ids: list[int] = []
    for line in body.split("\n"):
        line = line.rstrip()
        if not line.strip():
            continue
        scene = _SCENE_RE.match(line.strip())
        if scene:
            track = f"场{scene.group(1)} {scene.group(2).strip()}"
            continue
        if _SEG_RE.match(line.strip()):
            seg_asset_ids = []
            continue
        ids = _ASSET_IDS_RE.search(line)
        if ids:
            seg_asset_ids = [int(x) for x in _re.findall(r"\d+", ids.group(1))]
            continue
        if line.strip().startswith("|"):
            cells = [c.strip() for c in _ROW_SPLIT_RE.split(line.strip().strip("|"))]
            if len(cells) < 3 or cells[0] in ("序号", "") or set(cells[0]) <= set("-: "):
                continue
            desc = cells[1]
            extra = [c for c in cells[3:5] if c]  # 景别 / 运镜
            video_desc = desc + (f"（{'·'.join(extra)}）" if extra else "")
            tail = [c for c in cells[5:7] if c]  # 台词 / 音效
            if tail:
                video_desc += "\n" + "\n".join(tail)
            try:
                duration = int(float(cells[2]))
            except (ValueError, TypeError):
                duration = 4
            rows.append({"video_desc": video_desc, "duration": max(1, duration),
                         "asset_ids": seg_asset_ids, "track": track or "main"})
    if not rows:
        return 0

    with session_scope_ctx() as session:
        if script_id is None:
            s = session.scalars(select(TfScript).where(
                TfScript.projectId == project_id).order_by(TfScript.id.desc())).first()
            script_id = s.id if s else None
        session.query(TfStoryboard).filter(TfStoryboard.projectId == project_id).delete()
        for i, r in enumerate(rows):
            session.add(TfStoryboard(
                projectId=project_id, scriptId=script_id,
                videoDesc=r["video_desc"], duration=r["duration"],
                track=r["track"], assetIds=json.dumps(r["asset_ids"], ensure_ascii=False),
                shouldGenerateImage=True, orderNo=i + 1,
            ))
    print(f"[toonflow:storyboard] persist_markdown project={project_id} rows={len(rows)}")
    return len(rows)


def polish_storyboard_prompts_sync(project_id: int) -> None:
    """同步版分镜面板生成（Agent 工具直接调用，阻塞至完成）。"""
    _polish_prompts_job(project_id)


def _polish_prompts_job(project_id: int) -> None:
    with session_scope_ctx() as session:
        project = session.get(TfProject, project_id)
        boards = session.scalars(select(TfStoryboard).where(
            TfStoryboard.projectId == project_id).order_by(TfStoryboard.orderNo)).all()
        items = [{"id": b.id, "videoDesc": b.videoDesc} for b in boards]
        if not items:
            return
        assets = _assets_text(session, project_id)
        style_prefix = common.art_style_prefix(project)
        system = common.skill_body("production_execution_storyboard_panel.md")

    prompt = (f"资产清单：\n{assets}\n\n画风约束：\n{style_prefix or '（未设定）'}\n\n分镜列表：\n"
              + json.dumps(items, ensure_ascii=False)
              + '\n\n请为每条分镜输出分镜图提示词，直接输出 JSON：{"storyboardItems": [{"id": <id>, "prompt": "英文生图提示词"}]}')
    data = common.parse_json(common.llm(prompt, system=system, json_mode=True, project_id=project_id))
    out = {str(x.get("id")): str(x.get("prompt") or "") for x in (data.get("storyboardItems") or [])}
    if not out:
        raise RuntimeError("分镜面板生成结果为空")

    with session_scope_ctx() as session:
        boards = session.scalars(select(TfStoryboard).where(
            TfStoryboard.projectId == project_id)).all()
        for b in boards:
            p = out.get(str(b.id))
            if p:
                b.prompt = (style_prefix + "\n" + p).strip() if style_prefix else p
    print(f"[toonflow:storyboard] prompts project={project_id} count={len(out)}")


def _gen_image_for_board(board_id: int) -> None:
    from backend.toonflow.engines import Ai
    from backend.toonflow.core.paths import copy_into_oss

    with session_scope_ctx() as session:
        b = session.get(TfStoryboard, board_id)
        if b is None:
            return
        project_id = b.projectId
        refs = []
        for aid in json.loads(b.assetIds or "[]"):
            asset = session.get(TfAsset, int(str(aid).lstrip("Aa")))
            if asset and asset.imageId:
                img = session.get(TfImage, asset.imageId)
                if img and img.filePath:
                    refs.append(str(img.filePath))
        prompt = b.prompt or b.videoDesc
        b.state = "生成中"
        project = session.get(TfProject, project_id)
        # 分镜图跟随项目设定：图片质量 + 画面比例
        quality = (getattr(project, "imageQuality", "") or "").strip() or "1K"
        ratio = (getattr(project, "videoRatio", "") or "").strip() or "16:9"

    if not prompt.strip():
        raise ValueError(f"分镜 {board_id} 缺少提示词")
    out = Ai.image.run({"prompt": prompt, "referenceList": refs,
                        "resolution": quality, "aspectRatio": ratio},
                       project_id=project_id)

    with session_scope_ctx() as session:
        b = session.get(TfStoryboard, board_id)
        if b is None:
            return
        oss_path = copy_into_oss(out.first, project_id, "images")
        b.filePath = str(oss_path)
        b.state = "已完成"


def generate_storyboard_images(project_id: int, storyboard_ids: list[int] | None = None) -> dict:
    """批量生成/重生分镜图（异步，只处理 shouldGenerateImage 且有提示词的分镜）。"""
    with session_scope_ctx() as session:
        stmt = select(TfStoryboard).where(TfStoryboard.projectId == project_id)
        if storyboard_ids:
            stmt = stmt.where(TfStoryboard.id.in_([int(i) for i in storyboard_ids]))
        targets = [b.id for b in session.scalars(stmt).all()
                   if b.shouldGenerateImage and (b.prompt or "").strip()]
    for bid in targets:
        submit(_gen_image_for_board, bid)
    return {"queued": len(targets)}


def delete_storyboard(storyboard_id: int) -> None:
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        b = session.get(TfStoryboard, storyboard_id)
        if b:
            session.delete(b)
