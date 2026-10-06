import asyncio
import random
import time
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import async_session
from app.models.strategy import Strategy, StrategyRule
from app.models.api_key import ApiKey
from app.models.rotation_state import RotationState


class KeyUsageTracker:
    """Track per-key usage for threshold-based switching."""

    def __init__(self):
        self._rpm_times: dict[int, list[float]] = defaultdict(list)
        self._total_counts: dict[int, int] = defaultdict(int)

    def record_usage(self, key_id: int):
        now = time.time()
        self._rpm_times[key_id].append(now)
        self._total_counts[key_id] += 1
        # Clean old entries (older than 60s)
        cutoff = now - 60
        self._rpm_times[key_id] = [t for t in self._rpm_times[key_id] if t > cutoff]

    def get_rpm(self, key_id: int) -> int:
        now = time.time()
        cutoff = now - 60
        return sum(1 for t in self._rpm_times[key_id] if t > cutoff)

    def get_total(self, key_id: int) -> int:
        return self._total_counts[key_id]

    def is_over_rpm(self, key_id: int, threshold: int) -> bool:
        if threshold <= 0:
            return False
        return self.get_rpm(key_id) >= threshold

    def is_over_count(self, key_id: int, threshold: int) -> bool:
        if threshold <= 0:
            return False
        return self.get_total(key_id) >= threshold


# Global tracker instance
_key_tracker = KeyUsageTracker()


class RuleTokenTracker:
    """Track per-rule token usage for threshold-based switching with time windows."""

    PERIOD_SECONDS = {
        "per_minute": 60,
        "per_5min": 300,
        "per_day": 86400,
        "per_month": 2592000,
    }

    def __init__(self):
        # key: (strategy_id, rule_id), value: {"amount": int, "window_start": float}
        self._usage: dict[tuple[int, int], dict] = {}

    def _get_window(self, period: str) -> float:
        return self.PERIOD_SECONDS.get(period, 86400)

    def is_over_threshold(self, strategy_id: int, rule_id: int, threshold: int, period: str) -> bool:
        if threshold <= 0:
            return False
        key = (strategy_id, rule_id)
        entry = self._usage.get(key)
        if not entry:
            return False
        window = self._get_window(period)
        if time.time() - entry["window_start"] >= window:
            return False  # Window expired
        return entry["amount"] >= threshold

    def record_usage(self, strategy_id: int, rule_id: int, tokens: int, period: str):
        key = (strategy_id, rule_id)
        entry = self._usage.get(key)
        window = self._get_window(period)
        now = time.time()
        if not entry or (now - entry["window_start"]) >= window:
            self._usage[key] = {"amount": tokens, "window_start": now}
        else:
            entry["amount"] += tokens


# Global rule token tracker instance
_rule_token_tracker = RuleTokenTracker()


class RotationIndex:
    """Cross-request round-robin counter, persisted to DB so restarts resume.

    In-memory cache avoids a DB read per request; every selection writes the
    new counter back to the rotation_states table (single row upsert).
    """

    def __init__(self):
        self._cache: dict[str, int] = {}
        self._loaded: set[str] = set()
        self._lock = asyncio.Lock()

    async def next(self, scope: str, length: int) -> int:
        if length <= 0:
            return 0
        async with self._lock:
            if scope not in self._loaded:
                try:
                    await self._load(scope)
                except Exception:
                    pass  # fall back to 0; retry load on next call
                else:
                    self._loaded.add(scope)
            counter = self._cache.get(scope, 0)
            self._cache[scope] = counter + 1
            try:
                await self._persist(scope, counter + 1)
            except Exception:
                pass  # rotation still works; worst case restart resumes from an older counter
        return counter % length

    async def _load(self, scope: str):
        async with async_session() as session:
            result = await session.execute(
                select(RotationState).where(RotationState.scope == scope)
            )
            state = result.scalar_one_or_none()
            if state:
                self._cache[scope] = state.rr_index or 0

    async def _persist(self, scope: str, value: int):
        # Dedicated session so caller transactions are untouched
        async with async_session() as session:
            result = await session.execute(
                select(RotationState).where(RotationState.scope == scope)
            )
            state = result.scalar_one_or_none()
            if state is None:
                session.add(RotationState(scope=scope, rr_index=value))
            else:
                state.rr_index = value
            await session.commit()


# Global rotation index instance
_rotation_index = RotationIndex()


class Balancer:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def select_rule(
        self, strategy: Strategy, exclude_rule_ids: set | None = None
    ) -> StrategyRule | None:
        result = await self.db.execute(
            select(StrategyRule)
            .where(StrategyRule.strategy_id == strategy.id, StrategyRule.is_active == True)
            .order_by(StrategyRule.priority, StrategyRule.id)
        )
        rules = list(result.scalars().all())
        if not rules:
            return None

        # 重试时排除已失败的规则，实现真正的 failover；
        # 若所有规则都已被排除，则回退为原列表（重试总比直接失败好）
        if exclude_rule_ids:
            remaining = [r for r in rules if r.id not in exclude_rule_ids]
            rules = remaining or rules

        method = strategy.lb_strategy

        if method == "round_robin":
            idx = await _rotation_index.next(f"rule_{strategy.id}", len(rules))
            return rules[idx]

        elif method == "weighted":
            total_weight = sum(r.weight for r in rules)
            if total_weight == 0:
                return rules[0]
            pick = random.uniform(0, total_weight)
            current = 0
            for r in rules:
                current += r.weight
                if pick <= current:
                    return r
            return rules[-1]

        elif method == "random":
            return random.choice(rules)

        elif method == "failover":
            return rules[0]

        elif method == "priority":
            return rules[0]

        elif method == "token_threshold":
            threshold = strategy.rule_token_threshold
            period = strategy.rule_token_period or "per_day"
            eligible = [r for r in rules if not _rule_token_tracker.is_over_threshold(
                strategy.id, r.id, threshold, period
            )]
            if not eligible:
                eligible = rules  # All over threshold, fallback
            return eligible[0]

        return rules[0]

    async def select_key(
        self, provider_id: int, strategy: Strategy | None = None,
        exclude_key_ids: set | None = None,
    ) -> ApiKey | None:
        """Select an API key based on strategy's key_strategy and switch thresholds.

        取 key 规则（避免"连不通就把整个 provider 判死"）：
        1. 先把冷却到期的 rate_limited key 自动恢复为 active；
        2. 候选池 = 该 provider 下全部 key（除 exclude_key_ids），
           优先 status 为 active/untested 或限流已冷却的；
        3. 一个可用 key 都没有时，回退到全部 key（宁可试一把，也不直接失败）。
        """
        from app.utils.key_health import is_usable, restore_due_keys

        await restore_due_keys(self.db, provider_id)

        result = await self.db.execute(
            select(ApiKey)
            .where(ApiKey.provider_id == provider_id)
            .order_by(ApiKey.id)
        )
        keys = list(result.scalars().all())
        if not keys:
            return None

        if exclude_key_ids:
            remaining = [k for k in keys if k.id not in exclude_key_ids]
            keys = remaining or keys

        usable = [k for k in keys if is_usable(k.status, k.status_until)]
        pool = usable or keys

        if not strategy:
            # Fallback: weighted random
            return self._weighted_random(pool)

        key_method = strategy.key_strategy
        switch_mode = strategy.key_switch_mode
        rpm_threshold = strategy.key_rpm_threshold
        count_threshold = strategy.key_count_threshold

        # Filter out keys that have hit their threshold
        eligible = []
        for k in pool:
            over_rpm = switch_mode in ("rpm_threshold", "both") and _key_tracker.is_over_rpm(k.id, rpm_threshold)
            over_count = switch_mode in ("count_threshold", "both") and _key_tracker.is_over_count(k.id, count_threshold)
            if not over_rpm and not over_count:
                eligible.append(k)

        # If all keys are throttled, fall back to the whole pool (best effort)
        if not eligible:
            eligible = pool

        # Apply key strategy
        if key_method == "round_robin":
            selected = await self._round_robin_key(eligible, provider_id)
        elif key_method == "random":
            selected = random.choice(eligible)
        elif key_method == "failover":
            selected = eligible[0]
        else:
            selected = self._weighted_random(eligible)

        # Record usage
        if selected:
            _key_tracker.record_usage(selected.id)

        return selected

    async def _round_robin_key(self, keys: list[ApiKey], provider_id: int) -> ApiKey | None:
        """Round-robin across keys of one provider, persisted across requests/restarts."""
        if not keys:
            return None
        idx = await _rotation_index.next(f"key_{provider_id}", len(keys))
        return keys[idx]

    def _weighted_random(self, keys: list[ApiKey]) -> ApiKey:
        if not keys:
            return None
        total = sum(k.weight for k in keys)
        if total == 0:
            return keys[0]
        pick = random.uniform(0, total)
        current = 0
        for k in keys:
            current += k.weight
            if pick <= current:
                return k
        return keys[-1]

    def get_key_usage(self, key_id: int) -> dict:
        """Get usage stats for a key (for debugging/display)."""
        return {
            "rpm": _key_tracker.get_rpm(key_id),
            "total": _key_tracker.get_total(key_id),
        }
