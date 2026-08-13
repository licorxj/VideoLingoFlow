from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.models.log import RequestLog
from app.schemas.schemas import LogOut, PaginatedResponse

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=PaginatedResponse)
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    strategy_id: Optional[int] = None,
    provider_id: Optional[int] = None,
    status_code: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(RequestLog)
    count_query = select(func.count()).select_from(RequestLog)

    if strategy_id:
        query = query.where(RequestLog.strategy_id == strategy_id)
        count_query = count_query.where(RequestLog.strategy_id == strategy_id)
    if provider_id:
        query = query.where(RequestLog.provider_id == provider_id)
        count_query = count_query.where(RequestLog.provider_id == provider_id)
    if status_code:
        query = query.where(RequestLog.status_code == status_code)
        count_query = count_query.where(RequestLog.status_code == status_code)
    if start_date:
        dt = datetime.fromisoformat(start_date)
        query = query.where(RequestLog.created_at >= dt)
        count_query = count_query.where(RequestLog.created_at >= dt)
    if end_date:
        dt = datetime.fromisoformat(end_date)
        query = query.where(RequestLog.created_at <= dt)
        count_query = count_query.where(RequestLog.created_at <= dt)

    total = await db.scalar(count_query)
    query = query.order_by(RequestLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = [LogOut.model_validate(r) for r in result.scalars().all()]

    return PaginatedResponse(items=items, total=total or 0, page=page, page_size=page_size)
