"""GPU 服务状态 API：显存、lane 数、队列深度等。"""
import json

from fastapi import APIRouter

from backend.gpu_service import config, jobs

router = APIRouter(prefix="/gpu-service", tags=["gpu-service"])


@router.get("/status")
async def status():
    rc = jobs.get_redis()
    info = {}
    try:
        raw = rc.get(config.status_key())
        if raw:
            info = json.loads(raw)
    except Exception:
        pass
    try:
        available = jobs.service_alive(rc)
    except Exception:
        available = False
    return {
        "enabled": config.enabled(),
        "available": available,
        "max_lanes": config.max_lanes(),
        "idle_timeout": config.lane_idle_timeout(),
        "vram_headroom_gb": config.vram_headroom_gb(),
        **info,
    }
