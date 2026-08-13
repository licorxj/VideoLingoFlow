from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.strategy import Strategy, StrategyRule
from app.models.model import Model
from app.schemas.schemas import (
    StrategyCreate, StrategyUpdate, StrategyOut, StrategyRuleUpdate, StrategyRuleOut, StrategyTestResult,
)
import time

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _build_response(strategy, rules_list):
    return {
        "id": strategy.id, "name": strategy.name, "description": strategy.description or "",
        "lb_strategy": strategy.lb_strategy,
        "key_strategy": getattr(strategy, "key_strategy", "round_robin"),
        "key_switch_mode": getattr(strategy, "key_switch_mode", "none"),
        "key_rpm_threshold": getattr(strategy, "key_rpm_threshold", 0),
        "key_count_threshold": getattr(strategy, "key_count_threshold", 0),
        "is_active": strategy.is_active,
        "timeout": strategy.timeout, "retry_count": strategy.retry_count,
        "created_at": str(strategy.created_at) if strategy.created_at else None,
        "updated_at": str(strategy.updated_at) if strategy.updated_at else None,
        "rules": [
            {"id": r.id, "strategy_id": r.strategy_id, "provider_id": r.provider_id,
             "model_id": r.model_id, "priority": r.priority, "weight": r.weight, "model_name": r.model.model_id if r.model else str(r.model_id), "is_active": r.is_active}
            for r in rules_list
        ],
    }


@router.get("", response_model=list[StrategyOut])
async def list_strategies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Strategy).options(selectinload(Strategy.rules)).order_by(Strategy.id))
    return [_build_response(s, s.rules or []) for s in result.scalars().unique().all()]


@router.post("", response_model=StrategyOut, status_code=201)
async def create_strategy(data: StrategyCreate, db: AsyncSession = Depends(get_db)):
    strategy = Strategy(
        name=data.name, description=data.description, lb_strategy=data.lb_strategy,
        key_strategy=data.key_strategy, key_switch_mode=data.key_switch_mode,
        key_rpm_threshold=data.key_rpm_threshold, key_count_threshold=data.key_count_threshold,
        is_active=data.is_active, timeout=data.timeout, retry_count=data.retry_count,
    )
    db.add(strategy)
    await db.flush()
    for r in data.rules:
        db.add(StrategyRule(strategy_id=strategy.id, **r.model_dump()))
    await db.commit()
    result = await db.execute(select(Strategy).options(selectinload(Strategy.rules)).where(Strategy.id == strategy.id))
    s = result.scalar_one()
    return _build_response(s, s.rules or [])


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Strategy).options(selectinload(Strategy.rules)).where(Strategy.id == strategy_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Strategy not found")
    return _build_response(s, s.rules or [])


@router.put("/{strategy_id}")
async def update_strategy(strategy_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    data = StrategyUpdate(**body)

    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    for k, v in data.model_dump(exclude_unset=True, exclude={"rules"}).items():
        setattr(strategy, k, v)

    if data.rules is not None:
        await db.execute(sa_delete(StrategyRule).where(StrategyRule.strategy_id == strategy_id))
        await db.flush()
        for r in data.rules:
            db.add(StrategyRule(strategy_id=strategy_id, **r.model_dump()))
        await db.flush()

    await db.commit()

    rules_result = await db.execute(select(StrategyRule).where(StrategyRule.strategy_id == strategy_id))
    fresh_rules = list(rules_result.scalars().all())
    await db.refresh(strategy)
    return _build_response(strategy, fresh_rules)


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")
    await db.execute(sa_delete(StrategyRule).where(StrategyRule.strategy_id == strategy_id))
    await db.delete(strategy)
    await db.commit()


@router.post("/{strategy_id}/rules", response_model=StrategyRuleOut, status_code=201)
async def add_rule(strategy_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")
    rule = StrategyRule(strategy_id=strategy_id, **data)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=StrategyRuleOut)
async def update_rule(rule_id: int, data: StrategyRuleUpdate, db: AsyncSession = Depends(get_db)):
    rule = await db.get(StrategyRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    rule = await db.get(StrategyRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    await db.delete(rule)
    await db.commit()


@router.post("/{strategy_id}/test", response_model=StrategyTestResult)
async def test_strategy(strategy_id: int, db: AsyncSession = Depends(get_db)):
    from app.services.balancer import Balancer
    from app.services.forwarder import Forwarder

    result = await db.execute(select(Strategy).options(selectinload(Strategy.rules)).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    balancer = Balancer(db)
    rule = await balancer.select_rule(strategy)
    if not rule:
        return StrategyTestResult(success=False, message="No available rules")

    forwarder = Forwarder(db)
    start = time.monotonic()
    resp = await forwarder.send_test_request(strategy, rule)
    elapsed = int((time.monotonic() - start) * 1000)

    return StrategyTestResult(success=resp["success"], message=resp.get("message", ""),
                              latency_ms=elapsed, provider_used=resp.get("provider"), model_used=resp.get("model"))