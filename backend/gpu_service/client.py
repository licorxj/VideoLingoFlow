"""GPU Service 客户端：worker 侧步骤提交任务并等待结果。

- 服务不可用时抛 GpuServiceUnavailableError，上层回退进程内执行
- 等待期间把进度回调给 step；取消/超时由 step 的 callback 或本层超时触发
"""
import os

from backend.control_plane.runtime import TaskTimeoutError
from backend.gpu_service import config, jobs
from backend.gpu_service.jobs import GpuServiceUnavailableError

# manager 拉起 lane 子进程时注入该标记（见 manager._spawn_lane）
_LANE_ENV_FLAG = "GPU_SERVICE_LANE_WORKER"


def gpu_service_enabled() -> bool:
    # lane 子进程内不得再走服务代理：否则 separate/transcribe 会把任务递归提交回
    # GPU 队列，lane 等待自己需要执行的任务，lane 占满后形成死锁
    if os.getenv(_LANE_ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return config.enabled()


def service_available() -> bool:
    return jobs.service_alive()


def _submit_and_wait(kind: str, engine: str, params: dict, callback, timeout: float) -> dict:
    if not jobs.service_alive():
        raise GpuServiceUnavailableError("GPU 服务未启动或不可用")
    job_id = jobs.submit_job(kind, engine, params)
    rc = jobs.get_redis()
    if callback is not None:
        callback(0, "GPU 服务排队中")
    try:
        return jobs.wait_result(job_id, rc, timeout=max(timeout, 30.0), callback=callback)
    except TimeoutError:
        raise TaskTimeoutError(f"GPU 任务超时: {job_id}")
    except BaseException:
        # step callback 抛出的取消/超时等异常：通知 lane 停止
        jobs.request_cancel(job_id)
        raise


def run_asr(engine_name: str, input_path: str, output_path: str, *,
            model: str | None = None, language: str | None = None,
            engine_params: dict | None = None, callback=None, timeout: float = 3600) -> dict:
    """经 GPU 服务执行 ASR，返回引擎 transcribe 结果 dict。"""
    return _submit_and_wait("asr", engine_name, {
        "input_path": input_path,
        "output_path": output_path,
        "model": model or "",
        "language": language or "",
        "engine_params": engine_params or {},
    }, callback=callback, timeout=timeout)


def run_separation(iface_id: str, input_path: str, output_dir: str, *,
                   model: str = "", format: str = "", callback=None, timeout: float = 3600) -> dict:
    """经 GPU 服务执行人声分离，返回 {vocals, background} 路径 dict。"""
    return _submit_and_wait("separation", iface_id, {
        "input_path": input_path,
        "output_dir": output_dir,
        "model": model or "",
        "format": format or "",
    }, callback=callback, timeout=timeout)
