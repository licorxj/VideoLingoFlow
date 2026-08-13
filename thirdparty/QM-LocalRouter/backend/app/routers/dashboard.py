from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime
from app.database import get_db
from app.models.log import RequestLog
from app.models.strategy import Strategy
from app.models.provider import Provider
from app.models.api_key import ApiKey
from app.schemas.schemas import DashboardStats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    total = await db.scalar(select(func.count()).select_from(RequestLog).where(RequestLog.created_at >= today))
    success = await db.scalar(
        select(func.count()).select_from(RequestLog).where(
            RequestLog.created_at >= today, RequestLog.status_code.between(200, 299)
        )
    )
    errors = await db.scalar(
        select(func.count()).select_from(RequestLog).where(
            RequestLog.created_at >= today, ~RequestLog.status_code.between(200, 299)
        )
    )
    avg_lat = await db.scalar(
        select(func.avg(RequestLog.latency_ms)).select_from(RequestLog).where(RequestLog.created_at >= today)
    )

    # Token sums
    prompt_sum = await db.scalar(
        select(func.coalesce(func.sum(RequestLog.prompt_tokens), 0)).select_from(RequestLog).where(RequestLog.created_at >= today)
    )
    completion_sum = await db.scalar(
        select(func.coalesce(func.sum(RequestLog.completion_tokens), 0)).select_from(RequestLog).where(RequestLog.created_at >= today)
    )
    total_tok = await db.scalar(
        select(func.coalesce(func.sum(RequestLog.total_tokens), 0)).select_from(RequestLog).where(RequestLog.created_at >= today)
    )

    active_strats = await db.scalar(select(func.count()).select_from(Strategy).where(Strategy.is_active == True))
    active_provs = await db.scalar(select(func.count()).select_from(Provider).where(Provider.is_active == True))
    active_keys = await db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.status == "active"))

    total = total or 0
    success = success or 0
    errors = errors or 0

    return DashboardStats(
        total_requests=total,
        success_count=success,
        error_count=errors,
        success_rate=round(success / total * 100, 1) if total > 0 else 0.0,
        avg_latency_ms=round(avg_lat or 0, 1),
        total_prompt_tokens=prompt_sum or 0,
        total_completion_tokens=completion_sum or 0,
        total_tokens=total_tok or 0,
        active_strategies=active_strats or 0,
        active_providers=active_provs or 0,
        active_keys=active_keys or 0,
    )


@router.post("/clear-today")
async def clear_today_stats(db: AsyncSession = Depends(get_db)):
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    from sqlalchemy import delete
    result = await db.execute(delete(RequestLog).where(RequestLog.created_at >= today))
    await db.commit()
    return {"deleted": result.rowcount, "message": "Today's stats cleared"}
