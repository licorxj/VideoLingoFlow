# -*- coding: utf-8 -*-
"""资产阶段：出图 / 重生（提示词已由提取阶段生成，画风前缀已并入）。

出图：Ai.image({prompt, referenceList: 无}) → tf_images + asset.imageId 指向最新一张。
重生：保留旧候选，新增一张（对齐源 o_image 多候选语义）。
"""
from sqlalchemy import select

from backend.toonflow.core.models import TfAsset, TfImage
from backend.toonflow.core.paths import copy_into_oss
from backend.toonflow.pipeline import submit


def _generate_for_asset(asset_id: int) -> None:
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            return
        project_id = asset.projectId
        prompt = asset.prompt or asset.describe
        name = asset.name

    if not prompt.strip():
        raise ValueError(f"资产 {name} 缺少生图提示词")
    out = Ai_image_run(prompt, project_id)

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


def Ai_image_run(prompt: str, project_id: int):
    from backend.toonflow.engines import Ai

    return Ai.image.run({"prompt": prompt}, project_id=project_id)


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
