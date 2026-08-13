import random
import time
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.strategy import Strategy, StrategyRule
from app.models.api_key import ApiKey


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


class Balancer:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._rr_index: dict[int, int] = {}

    async def select_rule(self, strategy: Strategy) -> StrategyRule | None:
        result = await self.db.execute(
            select(StrategyRule)
            .where(StrategyRule.strategy_id == strategy.id, StrategyRule.is_active == True)
            .order_by(StrategyRule.priority, StrategyRule.id)
        )
        rules = result.scalars().all()
        if not rules:
            return None

        method = strategy.lb_strategy

        if method == "round_robin":
            idx = self._rr_index.get(strategy.id, 0) % len(rules)
            self._rr_index[strategy.id] = idx + 1
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

    async def select_key(self, provider_id: int, strategy: Strategy | None = None) -> ApiKey | None:
        """Select an API key based on strategy's key_strategy and switch thresholds."""
        result = await self.db.execute(
            select(ApiKey)
            .where(ApiKey.provider_id == provider_id, ApiKey.status.in_(["active", "untested"]))
            .order_by(ApiKey.id)
        )
        keys = result.scalars().all()
        if not keys:
            return None

        if not strategy:
            # Fallback: weighted random
            return self._weighted_random(keys)

        key_method = strategy.key_strategy
        switch_mode = strategy.key_switch_mode
        rpm_threshold = strategy.key_rpm_threshold
        count_threshold = strategy.key_count_threshold

        # Filter out keys that have hit their threshold
        eligible = []
        for k in keys:
            over_rpm = switch_mode in ("rpm_threshold", "both") and _key_tracker.is_over_rpm(k.id, rpm_threshold)
            over_count = switch_mode in ("count_threshold", "both") and _key_tracker.is_over_count(k.id, count_threshold)
            if not over_rpm and not over_count:
                eligible.append(k)

        # If all keys are throttled, fall back to all keys (best effort)
        if not eligible:
            eligible = keys

        # Apply key strategy
        if key_method == "round_robin":
            selected = self._round_robin_key(eligible)
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

    def _round_robin_key(self, keys: list[ApiKey]) -> ApiKey:
        """Round-robin across keys using a shared index keyed by the first key's provider."""
        if not keys:
            return None
        # Use provider_id from first key as the rr group key
        group = keys[0].provider_id
        idx = self._rr_index.get(f"key_{group}", 0) % len(keys)
        self._rr_index[f"key_{group}"] = idx + 1
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
