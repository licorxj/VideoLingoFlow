"""文件中转站 HTTP 接口。

提供中转站条目的查询（供节点弹窗与自动取件规则预览）与移除（软删除，不删磁盘文件）。
入库由工作流节点「文件中转站入库」在执行时自动完成，不在此处重复暴露。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.control_plane.security import require_permission
from backend.utils.file_transit import (
    FILE_TYPE_LABELS,
    ORDER_LABELS,
    list_files,
    pick_file,
    remove_file,
)

router = APIRouter()


@router.get("/meta", dependencies=[Depends(require_permission("workflow:read"))])
def transit_meta():
    """类型与排序规则的可选项，供前端卡片/弹窗下拉使用。"""
    return {
        "file_types": [{"value": "all", "label": "全部类型"}]
        + [{"value": key, "label": label} for key, label in FILE_TYPE_LABELS.items()],
        "orders": [{"value": key, "label": label} for key, label in ORDER_LABELS.items()],
    }


@router.get("/items", dependencies=[Depends(require_permission("workflow:read"))])
def transit_items(
    file_type: str = "all",
    keyword: str = "",
    order: str = "latest",
    limit: int = 100,
    offset: int = 0,
):
    """列出中转站条目（按类型/关键词过滤，按排序规则返回）。"""
    return list_files(file_type=file_type, keyword=keyword, order=order, limit=limit, offset=offset)


@router.get("/pick", dependencies=[Depends(require_permission("workflow:read"))])
def transit_pick(
    file_type: str = "all",
    keyword: str = "",
    order: str = "latest",
    index: int = 1,
    path: Optional[str] = None,
):
    """按规则预演取件结果，返回命中的一条（供卡片显示「将取到」）。"""
    item = pick_file(file_type=file_type, keyword=keyword, order=order, index=index, path=path or "")
    return {"item": item}


@router.delete("/items/{item_id}", dependencies=[Depends(require_permission("workflow:write"))])
def transit_remove(item_id: str):
    """移除一条中转站记录（只删登记，不动磁盘文件）。"""
    if not remove_file(item_id):
        raise HTTPException(404, "记录不存在或已删除")
    return {"success": True, "id": item_id}
