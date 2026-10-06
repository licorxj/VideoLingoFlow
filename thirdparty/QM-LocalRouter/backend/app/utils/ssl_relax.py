"""SSL 弹性策略（网关侧 async 版本）。

背景：`[SSL: CERTIFICATE_VERIFY_FAILED] Hostname mismatch, certificate is not
valid for 'api.agnes-ai.cn'` 属于间歇性故障（该域名证书本身正常，实测 SAN 含
*.agnes-ai.cn）。诱因通常是本地代理/中间人劫持、CDN 偶发返回默认站点证书、
DNS 污染到异常节点。

策略：按 host 分级降级并记忆成功档位，避免每次都握手失败拖慢请求：
    level 0 = httpx 默认（certifi，校验主机名）
    level 1 = 系统 CA + 只放宽主机名校验（证书链仍校验）
    level 2 = 完全不校验（默认禁用，需 QM_SSL_INSECURE=1 显式开启）

环境变量：
    QM_SSL_RELAX=0                     关闭降级（严格模式）
    QM_SSL_RELAX_HOSTS=a.com,b.com     限定哪些 host 允许降级（默认全部）
    QM_SSL_RELAX_TTL=300               降级档位记忆秒数
    QM_SSL_INSECURE=1                  允许 level 2

与主项目 backend/llm/direct_router.py 的同名策略保持一致。
"""
import os
import ssl
import time
from urllib.parse import urlsplit

import httpx


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


SSL_RELAX_ENABLED = _env_bool("QM_SSL_RELAX", True)
SSL_RELAX_INSECURE = _env_bool("QM_SSL_INSECURE", False)
SSL_RELAX_TTL = _env_int("QM_SSL_RELAX_TTL", 300)
SSL_LEVEL_CHAIN = [0, 1] + ([2] if SSL_RELAX_INSECURE else [])
_RELAX_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("QM_SSL_RELAX_HOSTS", "").split(",")
    if h.strip()
}

# host -> (降级档位, 记忆截止时间戳)
_relaxed: dict[str, tuple[int, float]] = {}


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def is_hostname_mismatch(exc: BaseException) -> bool:
    """沿异常链判断是否为「证书主机名不匹配」（而非过期/自签名等其它问题）。"""
    cur: BaseException | None = exc
    for _ in range(8):
        if cur is None:
            return False
        if isinstance(cur, ssl.SSLCertVerificationError):
            msg = str(getattr(cur, "verify_message", "") or cur).lower()
            return "hostname" in msg or "doesn't match" in msg or "not valid for" in msg
        cur = cur.__cause__ or cur.__context__
    return False


def relax_allowed(host: str) -> bool:
    if not SSL_RELAX_ENABLED or not host:
        return False
    if not _RELAX_HOSTS:
        return True
    return any(host == h or host.endswith("." + h) for h in _RELAX_HOSTS)


def current_level(host: str) -> int:
    level, until = _relaxed.get(host, (0, 0.0))
    if level and until > time.time():
        return level
    _relaxed.pop(host, None)
    return 0


def remember_level(host: str, level: int) -> None:
    if level <= 0:
        _relaxed.pop(host, None)
    else:
        _relaxed[host] = (level, time.time() + SSL_RELAX_TTL)


def verify_option(level: int):
    if level <= 0:
        return True
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    if level == 1:
        return ctx
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def client(timeout: float | int = 120, url: str | None = None,
           level: int | None = None) -> httpx.AsyncClient:
    """构造 AsyncClient；给了 url 就自动套用该 host 已记忆的降级档位。"""
    if level is None:
        level = current_level(host_of(url)) if url else 0
    return httpx.AsyncClient(
        timeout=timeout, trust_env=False, verify=verify_option(level)
    )


async def request_with_ssl_fallback(method: str, url: str, *, timeout: float | int = 120,
                                   **kwargs) -> httpx.Response:
    """发请求；证书 hostname 不匹配时按 host 逐级降级并记忆成功档位。

    仍失败则抛出原始异常，由调用方 failover 到下一个 provider/rule。
    """
    host = host_of(url)
    chain = SSL_LEVEL_CHAIN
    level = current_level(host)
    if level:
        chain = chain[chain.index(level):] if level in chain else [level]

    last_exc: Exception | None = None
    for idx, lv in enumerate(chain):
        async with client(timeout, level=lv) as c:
            try:
                return await c.request(method, url, **kwargs)
            except Exception as e:
                last_exc = e
                has_next = idx + 1 < len(chain)
                if has_next and relax_allowed(host) and is_hostname_mismatch(e):
                    nxt = chain[idx + 1]
                    print(
                        f"[ssl-relax] hostname mismatch on {host} "
                        f"({str(e)[:120]}) → 降级到 level {nxt} 重试",
                        flush=True,
                    )
                    remember_level(host, nxt)
                    continue
                raise
    raise last_exc  # pragma: no cover