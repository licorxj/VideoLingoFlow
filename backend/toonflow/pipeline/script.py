# -*- coding: utf-8 -*-
"""剧本阶段：剧本生成（事件→草稿，P3 换三层 Agent）与手动导入 / 资产提取。

资产提取使用 o_prompt 的 scriptAssetExtraction 模板——原文要求"必须经 resultTool 返回"，
单发调用时在 system 附加"以 JSON 输出替代 resultTool"的适配说明（隐式契约的显式化）。
"""
import json
import re

from sqlalchemy import select

from backend.toonflow.pipeline import common, submit
from backend.toonflow.core.models import TfAsset, TfNovel, TfProject, TfScript, TfScriptAsset

_VALID_TYPES = ("role", "scene", "tool")

# 上游模型（Qwen 系）无工具时会自行输出工具调用标记，或漏掉 <scriptItem> 包裹。
# 统一在落库前清洗，保证 tf_scripts.scriptData 永远是纯剧本正文。
_TOOL_CALL_BLOCK = re.compile(
    r"<(?:seed:)?tool_call\b[^>]*>[\s\S]*?(?:</(?:seed:)?tool_call>|$)", re.I)
_THINK_BLOCK = re.compile(r"<think>[\s\S]*?(?:</think>|$)", re.I)
_SCRIPT_ITEM = re.compile(
    r'<scriptItem\b[^>]*?\bname\s*=\s*["\']([^"\']*)["\'][^>]*>([\s\S]*?)</scriptItem\s*>', re.I)
_HEAD_TITLE = re.compile(r"^\s*#\s*(.+?)\s*$", re.M)


def clean_llm_text(text: str) -> str:
    """剥离工具调用 /思考标记等非剧本内容（上游模型越界输出的清洗）。"""
    out = _TOOL_CALL_BLOCK.sub("", str(text or ""))
    out = _THINK_BLOCK.sub("", out)
    return out.strip()


def extract_script_payload(text: str, default_title: str = "") -> tuple[str, str]:
    """LLM 文本 → (标题, 剧本正文)。

    优先取 <scriptItem name="...">…</scriptItem> 包裹的正文；否则回退到清洗后的全文，
    标题优先取标签 name、其次取文件头 `# 标题`，都没有则用 default_title。
    """
    cleaned = clean_llm_text(text)
    m = _SCRIPT_ITEM.search(cleaned)
    if m:
        name = (m.group(1) or "").strip()
        body = m.group(2).strip()
        head = _HEAD_TITLE.search(body)
        title = name or (head.group(1).strip() if head else "") or default_title
        return title, body

    head = _HEAD_TITLE.search(cleaned)
    title = (head.group(1).strip() if head else "") or default_title
    return title, cleaned


def _project_config_text(project: TfProject) -> str:
    """技能里的【项目配置】占位：用项目真实设置填充，避免模型自行臆测规格。"""
    if project is None:
        return ""
    ratio = project.videoRatio or "16:9"
    platform = "竖屏短视频（9:16）" if ratio == "9:16" else f"横屏 {ratio}"
    lines = [
        f"- 作品名：{project.name}",
        f"- 平台规格：{platform}",
        f"- 画风：{project.artStyle or '未设定'}",
        f"- 题材风格：{getattr(project, 'storyStyle', '') or '未设定'}",
        f"- 图片质量：{project.imageQuality or '1K'}",
    ]
    if (project.introduce or "").strip():
        lines.append(f"- 项目简介：{project.introduce.strip()[:300]}")
    return "\n".join(lines)


def add_script(project_id: int, title: str, script_data: str) -> int:
    """手动导入剧本。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        row = TfScript(projectId=project_id, title=title or "未命名剧本", scriptData=script_data or "")
        session.add(row)
        session.flush()
        return row.id


def _events_text(session, project_id: int, limit_chars: int = 24000) -> str:
    rows = session.scalars(select(TfNovel).where(TfNovel.projectId == project_id)).all()
    parts = [f"{r.chapter}：{r.event}" for r in rows if (r.event or "").strip()]
    return "\n".join(parts)[:limit_chars]


def generate_script_draft(project_id: int, title: str = "") -> dict:
    """按项目事件列表生成剧本草稿（同步）。

    技能文件要求模型先调 get_planData / get_novel_events / get_novel_text 取数据，
    但这里是单发调用（无工具），因此：
      1. 把工具本该返回的数据（项目配置 + 事件线）直接写进 prompt；
      2. system追加适配约束，禁止输出任何工具调用标记；
      3. 落库前解析 <scriptItem> 包裹、剥离工具调用残留（见 extract_script_payload）。
    """
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        events = _events_text(session, project_id)
        project = session.get(TfProject, project_id)
        config_text = _project_config_text(project)
        work_name = (project.name if project else "") or "未命名作品"
        skill = common.skill_body("script_execution_script.md")
        if not events:
            raise ValueError("项目还没有事件提取结果，请先完成事件提取")

    system = (skill + "\n\n## 输出方式适配（重要，优先遵守）\n"
              "本次运行没有 resultTool 之类的工具可用：技能中提到的 get_planData / "
              "get_novel_events / get_novel_text / get_script_content 的数据，已在用户消息中"
              "以【项目配置】与【事件线】的形式完整给出，**禁止输出任何工具调用标记**"
              "（如 tool_call 标签、seed:tool_call、function 调用块等），"
              "也不要调用工具或询问数据。\n"
              "请直接输出一对 <scriptItem name=\"剧本名称\">…</scriptItem> 标签包裹的完整剧本，"
              "标签之外不要输出任何内容（不要写阐述思路、不要写确认语）。")

    prompt = (f"【项目配置】\n{config_text or f'- 作品名：{work_name}'}\n\n"
              f"【事件线】\n{events}\n\n"
              f"请根据以上事件线，为《{work_name}》创作第1集完整剧本，"
              f"并用 <scriptItem> 标签包裹输出。")
    text = common.llm(prompt, system=system, json_mode=False, project_id=project_id)

    final_title, body = extract_script_payload(text, title or "Agent 剧本草稿")
    if not body.strip():
        raise ValueError("剧本生成结果为空（模型未返回剧本内容），请重试")
    script_id = add_script(project_id, final_title or (title or "Agent 剧本草稿"), body)
    print(f"[toonflow:script] draft script={script_id} project={project_id} chars={len(body)}")
    return {"script_id": script_id, "title": final_title, "chars": len(body)}


def extract_assets(script_id: int) -> dict:
    """触发资产提取（异步）：剧本 → role/scene/tool 资产清单。"""
    submit(_extract_assets_job, script_id)
    return {"queued": 1}


def _extract_assets_job(script_id: int) -> None:
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        script = session.get(TfScript, script_id)
        if script is None:
            return
        project_id = script.projectId
        script_text = script.scriptData or ""
        project = session.get(TfProject, project_id)
        template = common.prompt_by_type(session, "scriptAssetExtraction")
        script.extractState = 2  # 提取中（沿用源"进行中"语义：非0非1）

    system = (template
              + "\n\n## 输出方式适配（重要）\n本次运行没有 resultTool 工具。"
                "请直接输出 JSON 对象：{\"assetsList\": [{\"name\", \"desc\", \"prompt\", \"type\"}]}，"
                "type 取值 role/scene/tool，一次性给出全部资产，不要分批。")
    prompt = f"剧本内容：\n\n{script_text[:30000]}"
    data = common.parse_json(common.llm(prompt, system=system, json_mode=True, project_id=project_id))
    assets = data.get("assetsList") or []
    if not assets:
        with session_scope() as session:
            row = session.get(TfScript, script_id)
            if row:
                row.extractState = -1
        return

    created = 0
    with session_scope() as session:
        existing = {(a.name, a.type) for a in session.scalars(
            select(TfAsset).where(TfAsset.projectId == project_id)).all()}
        for item in assets:
            name = str(item.get("name") or "").strip()
            atype = str(item.get("type") or "").strip().lower()
            if not name or atype not in _VALID_TYPES or (name, atype) in existing:
                continue
            prompt_txt = str(item.get("prompt") or "").strip()
            # 对齐源：提取阶段不做画风注入，画风统一由「资产提示词润色」阶段
            # （art_skills 视觉手册，assets.polish_asset_prompts）语义级注入
            row = TfAsset(projectId=project_id, name=name, type=atype,
                          describe=str(item.get("desc") or ""), prompt=prompt_txt)
            session.add(row)
            session.flush()
            session.add(TfScriptAsset(scriptId=script_id, assetId=row.id))
            existing.add((name, atype))
            created += 1
        script_row = session.get(TfScript, script_id)
        if script_row:
            script_row.extractState = 1 if created or assets else -1
    print(f"[toonflow:script] extract_assets script={script_id} created={created}")


def asset_state(script_id: int) -> dict:
    """轮询：{state, assets:[...]}。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        script = session.get(TfScript, script_id)
        state = script.extractState if script else 0
        asset_ids = session.scalars(select(TfScriptAsset.assetId).where(
            TfScriptAsset.scriptId == script_id)).all()
        assets = []
        for aid in asset_ids:
            a = session.get(TfAsset, aid)
            if a:
                assets.append({"id": a.id, "name": a.name, "type": a.type,
                               "describe": a.describe, "prompt": a.prompt,
                               "imageId": a.imageId})
    return {"state": state, "assets": assets}
