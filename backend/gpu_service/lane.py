"""GPU Service lane：常驻工作子进程。

- 从本 lane 专属队列取任务执行（引擎首次使用时加载模型，之后常驻复用）
- 进度写入 Redis，供客户端回调；执行前/中检查取消标记
- 无任务达到空闲超时后自动退出，释放显存（由 manager 按需重新拉起）；
  空闲超时跟随 manager 发布的状态动态调整（显存紧张时自动缩短）
"""
import argparse
import json
import os
import signal
import sys
import threading
import time
import traceback

from backend.gpu_service import config, jobs


def _effective_idle_timeout(rc, default: int) -> int:
    """优先取 manager 发布的生效超时（显存紧张时更短）；状态缺失/过期则用默认值。"""
    try:
        raw = rc.get(config.status_key())
        if raw:
            status = json.loads(raw)
            if time.time() - float(status.get("ts", 0)) < 30:
                value = status.get("idle_timeout")
                if value:
                    return int(value)
    except Exception:
        pass
    return default


def _setup_project_path() -> None:
    """确保项目根目录在 sys.path（manager 以模块方式拉起时已设置，双保险）。"""
    current = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for parent in (current, os.getcwd()):
        if parent not in sys.path:
            sys.path.insert(0, parent)


def _progress(rc, job_id, pct, msg: str) -> None:
    jobs.push_progress(rc, job_id, pct, msg)
    if jobs.cancelled(rc, job_id):
        from backend.control_plane.runtime import TaskCancelledError
        raise TaskCancelledError("GPU 任务已取消")


def _run_asr(rc, job_id: str, engine_name: str, params: dict) -> dict:
    from backend.asr.asr_factory import get_asr_engine

    def cb(pct, msg):
        _progress(rc, job_id, pct, msg)

    engine = get_asr_engine(engine_name)
    # 模型加载/推理期间标记为 busy，避免 IdleEngineRegistry 的 5s 空闲清扫线程
    # 在加载途中误卸载引擎（moss 等大模型加载远超过空闲阈值）
    engine._busy = True
    try:
        return engine.transcribe(
            params["input_path"],
            params["output_path"],
            callback=cb,
            model=params.get("model"),
            language=params.get("language"),
            **params.get("engine_params", {}),
        )
    finally:
        engine._busy = False


def _run_separation(rc, job_id: str, iface_id: str, params: dict) -> dict:
    from backend.separation.separation_factory import get_separation_engine

    def cb(pct, msg):
        _progress(rc, job_id, pct, msg)

    engine = get_separation_engine(iface_id)
    return engine.separate(
        params["input_path"],
        params["output_dir"],
        cb,
        model=params.get("model"),
        format=params.get("format"),
    )


def _process_job(rc, lane_id: str, job: dict) -> None:
    job_id = job["job_id"]
    jobs.heartbeat(rc, lane_id, {"status": "busy", "job_id": job_id, "kind": job.get("kind"), "engine": job.get("engine"), "pid": os.getpid()})
    # 长任务期间持续心跳，避免 manager 误判空闲释放
    stop_hb = threading.Event()

    def _heartbeat_loop():
        while not stop_hb.is_set():
            jobs.heartbeat(rc, lane_id, {"status": "busy", "job_id": job_id, "pid": os.getpid()})
            stop_hb.wait(10.0)

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()
    start = time.time()
    try:
        kind = job.get("kind")
        if kind == "asr":
            result = _run_asr(rc, job_id, job["engine"], job.get("params", {}))
        elif kind == "separation":
            result = _run_separation(rc, job_id, job["engine"], job.get("params", {}))
        else:
            raise ValueError(f"未知 GPU 任务类型: {kind}")
        jobs.push_result(rc, job_id, result if isinstance(result, dict) else {"result": result})
        print(f"[GPU-lane {lane_id}] job {job_id[:8]} OK ({time.time() - start:.1f}s)", flush=True)
    except Exception as exc:
        traceback.print_exc()
        jobs.push_result(rc, job_id, {}, error=f"{type(exc).__name__}: {exc}"[:2000])
        print(f"[GPU-lane {lane_id}] job {job_id[:8]} FAILED: {exc}", flush=True)
    finally:
        stop_hb.set()
        jobs.heartbeat(rc, lane_id, {"status": "idle", "pid": os.getpid()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane-id", required=True)
    args = parser.parse_args()
    lane_id = args.lane_id
    _setup_project_path()
    rc = jobs.get_redis()
    idle_timeout = config.lane_idle_timeout()

    def _shutdown(signum, frame):
        print(f"[GPU-lane {lane_id}] signal {signum}, exit", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print(f"[GPU-lane {lane_id}] started pid={os.getpid()} idle_timeout={idle_timeout}s", flush=True)
    idle_since = time.time()
    while True:
        job = jobs.pop_lane_job(rc, lane_id, timeout=1.0)
        if job is not None:
            idle_since = time.time()
            _process_job(rc, lane_id, job)
            continue
        if time.time() - idle_since > _effective_idle_timeout(rc, idle_timeout):
            print(f"[GPU-lane {lane_id}] idle timeout reached, exit to release VRAM", flush=True)
            break
    jobs.clear_lane(lane_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
