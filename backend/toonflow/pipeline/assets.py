# -*- coding: utf-8 -*-
"""资产阶段：提示词润色（视觉手册注入画风）/ 出图（buildPrompt 任务包装）/ 重生。

对齐源 Toonflow：
    polishAssetsPrompt  system=art_skills/<画风>/art_prompt/<手册>（prefix.md 自动拼接）
    generateAssets      buildPrompt 结构化任务指令（角色标准四视图/标准场景图/标准道具图）
出图：Ai.image({prompt, referenceList}) → tf_images + asset.imageId 指向最新一张。
重生：保留旧候选，新增一张（对齐源 o_image 多候选语义）。
"""
from sqlalchemy import select

from backend.toonflow.core.models import TfAsset, TfImage, TfProject
from backend.toonflow.core.paths import copy_into_oss
from backend.toonflow.pipeline import common, submit, session_scope_ctx


# 生图任务指令包装（对齐源 generateAssets.buildPrompt / assetTypeConfig）
_TYPE_CFG = {
    "role": {"label": "角色", "promptTitle": "角色标准四视图", "promptEnd": "人物角色四视图"},
    "scene": {"label": "场景", "promptTitle": "标准场景图", "promptEnd": "标准场景图"},
    "tool": {"label": "道具", "promptTitle": "标准道具图", "promptEnd": "标准道具图"},
}


def _build_image_prompt(cfg: dict, art_style: str, name: str, prompt: str) -> str:
    return (
        f"请根据以下参数生成{cfg['promptTitle']}：\n\n"
        f"**基础参数：**\n- 画风风格: {art_style or '未指定'}\n\n"
        f"**{cfg['label']}设定：**\n- 名称:{name},\n- 提示词:{prompt},\n\n"
        f"请严格按照系统规范生成{cfg['promptEnd']}。"
    )


def _generate_for_asset(asset_id: int) -> None:
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.paths import from_rel

    with session_scope() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            return
        project_id = asset.projectId
        name = asset.name
        project = session.get(TfProject, project_id)
        # 项目图片质量（1K/2K/4K）
        quality = (getattr(project, "imageQuality", "") or "").strip() or "1K"
        art_style = getattr(project, "artStyle", "") or ""

    # 提示词缺失（如 Agent 新建的衍生资产）→ 先自动润色（视觉手册注入画风）
    if not (asset.prompt or "").strip():
        try:
            _polish_one(asset_id)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"资产 {name} 缺少提示词且自动润色失败: {exc}") from exc

    with session_scope() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            return
        prompt = (asset.prompt or "").strip() or (asset.describe or "").strip()
        cfg = _TYPE_CFG.get(asset.type, _TYPE_CFG["role"])
        # 参考图：重生带自身当前图；衍生资产带父资产图（对齐源 referenceList 语义）
        refs = []
        for img_id in ([asset.imageId] if asset.imageId else []) + (
                [session.get(TfAsset, asset.assetsId).imageId]
                if asset.assetsId and (p := session.get(TfAsset, asset.assetsId)) and p.imageId else []):
            img = session.get(TfImage, img_id) if img_id else None
            if img and img.filePath:
                refs.append(str(from_rel(img.filePath)))
        refs = list(dict.fromkeys(refs))

    if not prompt:
        raise ValueError(f"资产 {name} 缺少生图提示词")
    final_prompt = _build_image_prompt(cfg, art_style, name, prompt)
    out = Ai_image_run(final_prompt, project_id, quality, refs=refs or None)

    with session_scope() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            return
        oss_path = copy_into_oss(out.first, project_id, "images")
        img = TfImage(projectId=project_id, state="已完成", filePath=str(oss_path))
        session.add(img)
        session.flush()
        asset.imageId = img.id
        print(f"[toonflow:assets] asset={asset_id} image={img.id}")


def _art_manual_for(asset) -> str:
    """按资产类型/是否衍生选择视觉手册（对齐源 polishAssetsPrompt）。"""
    base = {"role": "art_character", "scene": "art_scene", "tool": "art_prop"}.get(asset.type, "art_character")
    if asset.assetsId is not None:  # 衍生资产
        base += "_derivative"
    return base


def _polish_one(asset_id: int) -> str:
    """单个资产提示词润色：视觉手册为 system，名称+描述为 user（对齐源 polishAssetsPrompt）。

    返回润色后的提示词；画风未设定或手册缺失时抛错（显式润色时用户可感知）。
    """
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            raise ValueError(f"资产不存在: {asset_id}")
        project = session.get(TfProject, asset.projectId)
        project_id, name, describe = asset.projectId, asset.name, asset.describe or ""
        style = getattr(project, "artStyle", "") if project else ""

    manual = common.get_art_prompt(style, _art_manual_for(asset))
    if not manual:
        raise ValueError(f"画风视觉手册缺失（项目画风：{style or '未设定'}），请先在项目设置中选择画风")

    prompt = common.llm(
        f"**基础参数：**\n"
        f"**{'角色' if asset.type == 'role' else '场景' if asset.type == 'scene' else '道具'}设定：**\n"
        f"- 名称:{name},\n- 描述:{describe},",
        system=manual, json_mode=False, project_id=project_id)
    prompt = str(prompt).strip()
    if not prompt:
        raise RuntimeError("提示词润色结果为空")

    with session_scope() as session:
        row = session.get(TfAsset, asset_id)
        if row is not None:
            row.prompt = prompt
    return prompt


def polish_asset_prompt(asset_id: int) -> dict:
    """润色单个资产提示词（异步）。"""
    submit(_polish_one, int(asset_id))
    return {"queued": 1, "assetId": asset_id}


def polish_asset_prompts(project_id: int, asset_ids: list[int] | None = None) -> dict:
    """批量润色（异步）。ids 缺省时处理项目内全部资产。"""
    with session_scope_ctx() as session:
        stmt = select(TfAsset).where(TfAsset.projectId == project_id)
        if asset_ids:
            stmt = stmt.where(TfAsset.id.in_([int(i) for i in asset_ids]))
        targets = [a.id for a in session.scalars(stmt).all()]
    for aid in targets:
        submit(_polish_one, aid)
    return {"queued": len(targets)}


def Ai_image_run(prompt: str, project_id: int, resolution: str = "", refs: list[str] | None = None):
    from backend.toonflow.engines import Ai

    return Ai.image.run({"prompt": prompt, "resolution": resolution or "1K",
                         "referenceList": refs or []},
                        project_id=project_id)


def generate_asset_images(asset_ids: list[int]) -> dict:
    """触发资产出图（异步）。"""
    for aid in asset_ids:
        submit(_generate_for_asset, int(aid))
    return {"queued": len(asset_ids)}


def regenerate_asset_image(asset_id: int) -> dict:
    """重生一张资产图（新增候选）。"""
    submit(_generate_for_asset, int(asset_id))
    return {"queued": 1}


def list_asset_ids_without_image(project_id: int) -> list[dict]:
    """还没有图的资产（Agent「补齐资产图」用）。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        rows = session.scalars(select(TfAsset).where(
            TfAsset.projectId == project_id, TfAsset.imageId.is_(None))).all()
        return [{"id": r.id, "name": r.name, "type": r.type} for r in rows]


def images_of_asset(asset_id: int) -> list[dict]:
    """资产的候选图列表（N 选 1 的数据基础）。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            return []
        rows = session.scalars(select(TfImage).where(
            TfImage.projectId == asset.projectId).order_by(TfImage.id.desc())).all()
        # P2 简化：图片表未回链 assetId，暂以 project 维度返回最新；候选关联在 P3 记忆化收口
        return [{"id": r.id, "filePath": r.filePath, "state": r.state} for r in rows[:20]]
