"""API Key 健康状态判定 —— 原则：**连不通 ≠ key 弃用**。

背景：历史实现里，只要一次探测/转发失败（非 200 一律算），key 就被写成
`inactive`；限流（429）写成 `rate_limited` 之后又没有任何恢复路径。结果是
「网络抖一下 / 上端 429 一次 → 整个 provider 再也选不出 key」，请求直接以
`no active API key for provider ...` 失败。

本模块把失败原因分级，只有「上游明确答复这个凭证不能用」才允许弃用：

|failure kind   | 触发条件                                | 对 key 的处理                |
|----------------|-----------------------------------------|------------------------------|
| ``auth``       | HTTP 401 / 403                          | 连续 N 次才置 inactive（默认 2）|
| ``rate_limit`` | HTTP 429                                | 置 rate_limited + 冷却截止时间 |
| ``config``     | HTTP 400/404/405/422（模型/路径/参数错） | 仅记录 last_error            |
| ``upstream``   | HTTP 5xx / 408                | 仅记录 last_error            |
| ``unreachable``| DNS/拒连/TLS/超时/断流（连不通）          | 仅记录 last_error            |
| ``unknown``    | 其它                                    | 仅记录 last_error            |

冷却到期的 ``rate_limited`` key 由 :func:`is_usable` / :func:`restore_due_keys`
自动复活，不需要人工干预。

环境变量：
- ``QM_KEY_AUTH_CONFIRM_THRESHOLD``  连续多少次 401/403 才弃用（默认 2，设 1 =旧行为）
- ``QM_KEY_RATE_LIMIT_COOLDOWN``     429 冷却秒数（默认 60，设 0 = 不冷却）
"""
import os
import time

# --- 可调阈值 ---------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


#: 连续多少次 401/403 才把 key 置为 inactive（1 = 旧行为，立即弃用）
AUTH_CONFIRM_THRESHOLD = _env_int("QM_KEY_AUTH_CONFIRM_THRESHOLD", 2)
#: 429 后的冷却秒数；到期自动恢复 active
RATE_LIMIT_COOLDOWN = _env_int("QM_KEY_RATE_LIMIT_COOLDOWN", 60)

AUTH_STATUS = (401, 403)
RATE_LIMIT_STATUS = (429,)

#: 这些状态属于「可用」，inactive/expired 才算不可用
USABLE_STATUS = ("active", "untested")

# httpx 传输层异常名（ConnectError/ReadTimeout/SSLError/...）→ 连不通
_TRANSPORT_EXC_NAMES = {
    "TransportError", "TimeoutException", "ConnectError", "ConnectTimeout",
    "ReadTimeout", "WriteTimeout", "PoolTimeout", "ReadError", "WriteError",
    "CloseError", "ProxyError", "UnsupportedProtocol", "LocalProtocolError",
    "RemoteProtocolError", "NetworkError", "SSLError", "SSLCertVerificationError",
    "OSError", "TimeoutError", "ConnectionError",
}


def now_ts() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# 失败原因分类
# ---------------------------------------------------------------------------
def classify_status_code(status_code: int | None) -> str:
    """把上游 HTTP 状态码归类为 failure kind。"""
    if status_code is None:
        return "unknown"
    code = int(status_code)
    if 200 <= code < 300:
        return "ok"
    if code in AUTH_STATUS:
        return "auth"
    if code in RATE_LIMIT_STATUS:
        return "rate_limit"
    if code in (408, 425, 409, 500, 502, 503, 504, 529):
        return "upstream"
    if code in (400, 404, 405, 422):
        # 模型名/路径/参数不对 —— 与 key 是否有效无关，绝不能据此弃用
        return "config"
    return "client_error"


def classify_exception(exc: BaseException) -> str:
    """把异常归类为 failure kind（连不通 → unreachable，永不弃用）。"""
    names = {c.__name__ for c in type(exc).__mro__}
    if "HTTPStatusError" in names:
        resp = getattr(exc, "response", None)
        return classify_status_code(getattr(resp, "status_code", None))
    if names & _TRANSPORT_EXC_NAMES:
        return "unreachable"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "unreachable"
    return "unknown"


#: 会不会影响 key 的可用状态（false = 只记录错误，不弃用）
DEGRADES_KEY = ("auth", "rate_limit")


# ---------------------------------------------------------------------------
# 状态判定
# ---------------------------------------------------------------------------
def is_usable(status: str | None, status_until: int | None = 0, now: int | None = None) -> bool:
    """key 现在能不能用。rate_limited 冷却到期即视为可用。"""
    st = (status or "active").lower()
    if st in USABLE_STATUS:
        return True
    if st == "rate_limited":
        return int(status_until or 0) <= (now or now_ts())
    return False


def cooldown_remaining(status_until: int | None, now: int | None = None) -> int:
    return max(0, int(status_until or 0) - (now or now_ts()))


def next_status(current_status: str | None, fail_count: int, kind: str,
                *, now: int | None = None, cooldown: int | None = None) -> tuple[str | None, int, int]:
    """根据失败原因算出新的 (status, fail_count, status_until)。

    - ``status`` 为 ``None`` 表示状态不变（调用方只更新 last_error）；
    - ``fail_count`` 是连续 auth 失败次数，其它原因不累加。
    """
    ts = now or now_ts()
    cur_fail = int(fail_count or 0)
    if kind == "ok":
        return "active", 0, 0
    if kind == "auth":
        cur_fail += 1
        if cur_fail >= max(1, AUTH_CONFIRM_THRESHOLD):
            return "inactive", cur_fail, 0
        # 尚未确认：保持原状态，仅累计失败次数
        return None, cur_fail, 0
    if kind == "rate_limit":
        cd = RATE_LIMIT_COOLDOWN if cooldown is None else int(cooldown)
        if cd > 0:
            return "rate_limited", cur_fail, ts + cd
        # 不冷却：保持原状态，下一次请求直接重试
        return None, cur_fail, 0
    # config / upstream / unreachable / client_error / unknown —— 连不通或配置问题，
    # 一律不改状态，避免好 key 被误杀。
    return None, cur_fail, 0


# ---------------------------------------------------------------------------
# ORM 便捷封装
# ---------------------------------------------------------------------------
def _get(obj, name, default):
    return getattr(obj, name, default) if obj is not None else default


def mark_success(key) -> str:
    """探测/调用成功：清错误、复位计数、清除冷却。"""
    key.status = "active"
    key.last_error = None
    if hasattr(key, "fail_count"):
        key.fail_count = 0
    if hasattr(key, "status_until"):
        key.status_until = 0
    return "active"


def mark_failure(key, kind: str, message: str = "") -> str:
    """按失败原因更新 key 状态，返回最终 status。"""
    status, fail_count, status_until = next_status(
        _get(key, "status", "active"), _get(key, "fail_count", 0), kind,
    )
    if status is not None:
        key.status = status
    if hasattr(key, "fail_count"):
        key.fail_count = fail_count
    if hasattr(key, "status_until"):
        key.status_until = status_until
    if message:
        key.last_error = message[:500]
    return getattr(key, "status", "active")


async def restore_due_keys(db, provider_id: int | None = None) -> int:
    """把冷却到期的 rate_limited key 自动恢复为 active，返回恢复条数。

    在选key（Balancer.select_key）时调用，实现「限流只冷却、不永久弃用」。
    """
    from sqlalchemy import update

    from app.models.api_key import ApiKey

    ts = now_ts()
    stmt = (
        update(ApiKey)
        .where(ApiKey.status == "rate_limited", ApiKey.status_until <= ts)
        .values(status="active", status_until=0, last_error=None)
    )
    if provider_id is not None:
        stmt = stmt.where(ApiKey.provider_id == provider_id)
    result = await db.execute(stmt)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
    return int(result.rowcount or 0)