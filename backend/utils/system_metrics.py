"""系统资源指标采集：后台常驻采样，接口零成本读取。

原先 ``/api/control/runtime/status`` 在每次请求里同步执行
``psutil.cpu_percent(interval=0.1)``（阻塞 100ms），并顺带做 Celery inspect、
Redis、DB 查询等重操作，导致头部 CPU/RAM/GPU/VRAM 指标既慢又抖。

此处改为「后台线程周期采样 + 内存缓存」：
- CPU / 内存：psutil，1 秒粒度，读写分离后请求侧不再阻塞；
- GPU 使用率 / 显存：直采 nvidia-smi（回退 torch、再回退 GPU 服务快照），
  这样即使 GPU 服务未启用也能拿到整卡真实数据；空闲/无卡时采样间隔自适应拉长。

前端通过 ``GET /api/control/system/metrics`` 读取本缓存，可高频轮询。
"""
import json
import threading
import time
from typing import Any

_CPU_INTERVAL = 1.0
_GPU_INTERVAL = 2.0
_GPU_MAX_INTERVAL = 30.0
_GPU_STALE_SECONDS = 15.0

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "available": False,
    "cpu_percent": None,
    "ram_percent": None,
    "gpu_percent": None,
    "vram_percent": None,
    "updated_at": 0.0,
}
_started = False
_start_lock = threading.Lock()


def _prime() -> None:
    """首帧同步填充一次 CPU/内存，避免接口前 1 秒返回空值。"""
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory().percent
        with _LOCK:
            _STATE["available"] = True
            _STATE["cpu_percent"] = round(float(cpu), 1)
            _STATE["ram_percent"] = round(float(ram), 1)
            _STATE["updated_at"] = time.time()
    except Exception:
        pass


def _sample_cpu_ram() -> None:
    try:
        import psutil
    except Exception:
        return
    while True:
        try:
            cpu = psutil.cpu_percent(interval=_CPU_INTERVAL)
            ram = psutil.virtual_memory().percent
            with _LOCK:
                _STATE["available"] = True
                _STATE["cpu_percent"] = round(float(cpu), 1)
                _STATE["ram_percent"] = round(float(ram), 1)
                _STATE["updated_at"] = time.time()
        except Exception:
            time.sleep(_CPU_INTERVAL)


def _gpu_snapshot() -> dict[str, Any]:
    """GPU 数据：优先直采（nvidia-smi → torch），失败再回退 GPU 服务快照。"""
    try:
        from backend.gpu_service.monitor import gpu_info

        info = gpu_info()
        if info.get("available"):
            return info
    except Exception:
        pass
    try:
        from backend.gpu_service import config as gpu_config
        from backend.gpu_service import jobs as gpu_jobs

        if gpu_config.enabled():
            raw = gpu_jobs.get_redis().get(gpu_config.status_key())
            if raw:
                status = json.loads(raw)
                vram = status.get("vram")
                if isinstance(vram, dict) and vram:
                    return vram
    except Exception:
        pass
    return {}


def _sample_gpu() -> None:
    """采集 GPU 数据；连续失败（无卡/无服务）时自适应拉长间隔降低开销。"""
    interval = _GPU_INTERVAL
    last_ok = 0.0
    while True:
        updated = False
        try:
            info = _gpu_snapshot()
            total = info.get("total_gb")
            used = info.get("used_gb")
            util = info.get("utilization_percent")
            with _LOCK:
                if isinstance(total, (int, float)) and total > 0 and isinstance(used, (int, float)):
                    _STATE["vram_percent"] = round(float(used) / float(total) * 100, 1)
                    updated = True
                if isinstance(util, (int, float)):
                    _STATE["gpu_percent"] = round(float(util), 1)
                    updated = True
        except Exception:
            pass

        now = time.time()
        if updated:
            last_ok = now
            interval = _GPU_INTERVAL
        else:
            # 长时间拿不到数据则清空，避免展示过期数值
            if last_ok and now - last_ok > _GPU_STALE_SECONDS:
                with _LOCK:
                    _STATE["gpu_percent"] = None
                    _STATE["vram_percent"] = None
            interval = min(interval * 2, _GPU_MAX_INTERVAL)
        time.sleep(interval)


def _ensure_started() -> None:
    global _started
    if _started:
        return
    with _start_lock:
        if _started:
            return
        _started = True
        _prime()
        threading.Thread(target=_sample_cpu_ram, name="system-metrics-cpu", daemon=True).start()
        threading.Thread(target=_sample_gpu, name="system-metrics-gpu", daemon=True).start()


def get_system_metrics() -> dict[str, Any]:
    """返回最近一次采样的系统指标（纯内存读取，不阻塞）。"""
    _ensure_started()
    with _LOCK:
        snapshot = dict(_STATE)
    updated_at = float(snapshot.get("updated_at") or 0)
    snapshot["age_seconds"] = round(max(0.0, time.time() - updated_at), 1) if updated_at else None
    return snapshot
