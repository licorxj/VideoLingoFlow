"""运行时系统通知 API：供前端头部通知中心轮询拉取。"""
from fastapi import APIRouter, Query

from backend.utils.runtime_notifications import list_notifications

router = APIRouter(tags=["notifications"])


@router.get("")
async def get_notifications(
    since: str = Query("", description="只返回 created_at 晚于该 ISO 时间的通知"),
    limit: int = Query(50, ge=1, le=200),
):
    items, server_time = list_notifications(since, limit)
    return {"notifications": items, "serverTime": server_time}
