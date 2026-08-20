"""GPU Service 配置：全部通过环境变量控制，默认值保证单卡安全。"""
import os


def enabled() -> bool:
    return os.getenv("GPU_SERVICE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def redis_url() -> str:
    return os.getenv("GPU_SERVICE_REDIS_URL") or os.getenv("CONTROL_PLANE_CELERY_BROKER_URL", "redis://127.0.0.1:6379/2")


def max_lanes() -> int:
    """lane 工作进程上限（显存充足时的最大并发路数）。"""
    return _int_env("GPU_SERVICE_MAX_LANES", 2)


def lane_idle_timeout() -> int:
    """lane 无任务空闲时长（秒），超时退出释放显存。"""
    return _int_env("GPU_SERVICE_LANE_IDLE_TIMEOUT", 600)


def pressure_idle_timeout() -> int:
    """显存紧张（free < 2×headroom）时的 lane 空闲超时（秒），显著短于常规值。"""
    return _int_env("GPU_SERVICE_PRESSURE_IDLE_TIMEOUT", 60)


def vram_headroom_gb() -> float:
    """剩余显存低于该值（GB）时不再分配新 lane（防 OOM 排队等待）。"""
    return _float_env("GPU_SERVICE_VRAM_HEADROOM_GB", 3.0)


def job_timeout() -> int:
    """单个任务执行上限（秒）。"""
    return _int_env("GPU_SERVICE_JOB_TIMEOUT", 3600)


def heartbeat_ttl() -> int:
    """lane 心跳 / 状态键 TTL（秒）。"""
    return _int_env("GPU_SERVICE_HEARTBEAT_TTL", 30)


def shutdown_key() -> str:
    return "videolingo:gpu:shutdown"


def status_key() -> str:
    return "videolingo:gpu:status"


def job_queue_key() -> str:
    return "videolingo:gpu:jobs"


def lane_queue_key(lane_id: str) -> str:
    return f"videolingo:gpu:lane:{lane_id}:jobs"


def result_key(job_id: str) -> str:
    return f"videolingo:gpu:result:{job_id}"


def progress_key(job_id: str) -> str:
    return f"videolingo:gpu:progress:{job_id}"


def cancel_key(job_id: str) -> str:
    return f"videolingo:gpu:cancel:{job_id}"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default
