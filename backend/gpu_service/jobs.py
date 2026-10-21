"""GPU Service 任务协议：Redis 队列 / 结果 / 进度 / 取消 / 心跳。"""
import json
import os
import time
import uuid

import redis

from backend.gpu_service import config

_JOB_TTL = 24 * 3600  # 结果/进度键保留时长
RESULT_LIMIT = 512 * 1024 * 1024  # 单个结果上限（Redis string/list 安全阈值）


class GpuServiceUnavailableError(RuntimeError):
    """GPU 服务不可用（未启动 / Redis 不可达 / manager 心跳过期）。"""


def get_redis(decode: bool = True) -> redis.Redis:
    return redis.Redis.from_url(config.redis_url(), decode_responses=decode)


def _now() -> float:
    return time.time()


def service_alive(client: redis.Redis | None = None) -> bool:
    """服务是否可用：Redis 可 ping 且（manager 心跳新鲜 或 任一 lane 心跳新鲜）。

    manager 状态键过期（重启/卡顿）但仍有 lane 在正常跑时，服务对提交/等待侧
    依然可用；此时若仅凭状态键判死，上层会误回退到无管控的进程内 CUDA 执行。
    """
    try:
        rc = client or get_redis()
        if not rc.ping():
            return False
        ttl = config.heartbeat_ttl()
        raw = rc.get(config.status_key())
        if raw:
            info = json.loads(raw)
            if (_now() - float(info.get("ts", 0))) <= ttl * 2:
                return True
        # manager 状态键不新鲜：退而检查 lane 心跳（busy 心跳 10s 一轮，idle 由 lane 自维护）
        hbs = read_heartbeats(rc)
        return any((_now() - float(h.get("ts", 0))) <= ttl for h in hbs.values())
    except Exception:
        return False


def submit_job(kind: str, engine: str, params: dict) -> str:
    """向服务队列提交任务，返回 job_id。"""
    job_id = uuid.uuid4().hex
    payload = {
        "job_id": job_id,
        "kind": kind,          # "asr" | "separation"
        "engine": engine,      # ASR engine 名 或 separation interface_id
        "params": params,      # input/output 路径、model、language、format 等
        "ts": _now(),
    }
    rc = get_redis()
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > RESULT_LIMIT:
        raise ValueError("GPU 任务参数过大")
    rc.lpush(config.job_queue_key(), encoded)
    return job_id


def wait_result(job_id: str, client: redis.Redis, timeout: float, callback=None, wait_step: float = 0.5) -> dict:
    """阻塞等待任务结果（BRPOP 结果键 + 轮询进度回调）。

    - 进度事件按到达顺序回调；为避免 worker 进度事件风暴，按 pct/message 变化才回调，
      同时每 5 秒发一次心跳回调（供上层取消/超时检测）。
    - 等待期间每 5 秒复检 manager 心跳：服务已死/不再调度时立即抛
      GpuServiceUnavailableError，让上层快速回退进程内执行，避免空等到超时。
    - 超时抛 TimeoutError；上层（step）据此转 TaskTimeoutError。
    """
    deadline = time.monotonic() + timeout
    last_pct = -1
    last_msg = ""
    last_heartbeat = 0.0
    last_alive_check = 0.0
    prog_idx = 0
    rkey = config.result_key(job_id)
    pkey = config.progress_key(job_id)
    while True:
        item = client.brpop(rkey, timeout=1)
        if item is not None:
            return _load_result(item[1])
        now = time.monotonic()
        if now - last_alive_check >= 5.0:
            last_alive_check = now
            if not service_alive(client):
                raise GpuServiceUnavailableError(f"GPU 服务等待期间失联: {job_id}")
        if callback is not None:
            try:
                events = client.lrange(pkey, 0, -1) or []
            except Exception:
                events = []
            total = len(events)
            # `push_progress` 用 LPUSH，列表 index 0 是**最新**事件；而 prog_idx
            # 记的是"已消费数量"，必须从未消费的**尾部**取（旧→新）。
            # 直接按 events[prog_idx:] 切片会漏掉所有新事件，导致界面永远停在
            # 第一条进度上并反复重发同一句话。
            pending = events[: max(0, total - prog_idx)][::-1]
            prog_idx = total
            forward = False
            for raw in pending:
                try:
                    ev = json.loads(raw)
                    pct = ev.get("pct", last_pct)
                    msg = ev.get("msg", "")
                except (TypeError, ValueError):
                    continue
                if pct != last_pct or msg != last_msg:
                    last_pct, last_msg = pct, msg
                    forward = True
            if forward or (now - last_heartbeat) >= 5.0:
                last_heartbeat = now
                callback(max(last_pct, 0), last_msg or "")
        if time.monotonic() >= deadline:
            _request_cancel(job_id)
            raise TimeoutError(f"GPU 任务超时: {job_id}")


def _load_result(raw) -> dict:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise RuntimeError("GPU 任务结果损坏")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data["error"])
    return data if isinstance(data, dict) else {"result": data}


def _request_cancel(job_id: str) -> None:
    try:
        rc = get_redis()
        rc.set(config.cancel_key(job_id), "1", ex=3600)
    except Exception:
        pass


def request_cancel(job_id: str) -> None:
    _request_cancel(job_id)


def push_progress(client: redis.Redis, job_id: str, pct, msg: str) -> None:
    client.lpush(config.progress_key(job_id), json.dumps({"pct": int(pct), "msg": str(msg)}, ensure_ascii=False))
    client.expire(config.progress_key(job_id), _JOB_TTL)


def push_result(client: redis.Redis, job_id: str, result: dict, error: str | None = None) -> None:
    data = {"error": error} if error else result
    client.lpush(config.result_key(job_id), json.dumps(data, ensure_ascii=False))
    client.expire(config.result_key(job_id), _JOB_TTL)
    client.expire(config.progress_key(job_id), _JOB_TTL)


def cancelled(client: redis.Redis, job_id: str) -> bool:
    return client.exists(config.cancel_key(job_id)) > 0


def heartbeat(client: redis.Redis, lane_id: str, info: dict) -> None:
    client.hset("videolingo:gpu:heartbeat", lane_id, json.dumps({**info, "ts": _now()}, ensure_ascii=False))
    client.expire("videolingo:gpu:heartbeat", config.heartbeat_ttl() * 3)


def read_heartbeats(client: redis.Redis) -> dict[str, dict]:
    raw = client.hgetall("videolingo:gpu:heartbeat") or {}
    result = {}
    for lane_id, payload in raw.items():
        try:
            result[lane_id] = json.loads(payload)
        except (TypeError, ValueError):
            continue
    return result


def publish_status(client: redis.Redis, status: dict) -> None:
    client.set(config.status_key(), json.dumps({**status, "ts": _now()}, ensure_ascii=False), ex=config.heartbeat_ttl() * 3)


def pop_job(client: redis.Redis, timeout: float = 1.0):
    """manager 侧：从共享任务队列取出一个任务（BRPOP）。"""
    item = client.brpop(config.job_queue_key(), timeout=int(max(0, timeout)))
    if item is None:
        return None
    try:
        return json.loads(item[1])
    except (TypeError, ValueError):
        return None


def push_lane_job(client: redis.Redis, lane_id: str, job: dict) -> None:
    client.lpush(config.lane_queue_key(lane_id), json.dumps(job, ensure_ascii=False))


def pop_lane_job(client: redis.Redis, lane_id: str, timeout: float = 1.0):
    """lane 侧：从本 lane 专属队列取任务（BRPOP，用于空闲退出判定）。"""
    item = client.brpop(config.lane_queue_key(lane_id), timeout=int(max(0, timeout)))
    if item is None:
        return None
    try:
        return json.loads(item[1])
    except (TypeError, ValueError):
        return None


def clear_lane(lane_id: str) -> None:
    """清理 lane 遗留的队列/心跳。"""
    try:
        rc = get_redis()
        rc.delete(config.lane_queue_key(lane_id))
        rc.hdel("videolingo:gpu:heartbeat", lane_id)
    except Exception:
        pass


def requeue_lane_jobs(client: redis.Redis, lane_id: str) -> int:
    """lane 退出时把其专属队列里的候补任务按原顺序搬回共享队列。

    队列语义：push_lane_job 用 LPUSH（左端最新），lane 侧 BRPOP 取右端（最旧）。
    因此 lrange 顺序为 [最新...最旧]；按该顺序 RPUSH 回共享队列后，最旧任务
    位于共享队列右端，仍会被优先消费，顺序不丢、不饿死。
    返回搬迁任务数；任何异常都静默返回 0（由 manager 日志层面感知）。
    """
    try:
        pending = client.lrange(config.lane_queue_key(lane_id), 0, -1)
        if not pending:
            return 0
        pipe = client.pipeline()
        pipe.delete(config.lane_queue_key(lane_id))
        pipe.rpush(config.job_queue_key(), *pending)
        pipe.execute()
        return len(pending)
    except Exception:
        return 0


def fail_orphan_job(client: redis.Redis, job_id: str, error: str) -> None:
    """lane 崩溃时给其「在途未产出」的任务补一个失败结果。

    没有这个补偿，等待方（wait_result 的 BRPOP）只能空等到超时（默认 3600s，
    本机环境变量可配到 7200s）才报错，表现为「任务卡住不动」。
    正常完成的任务会先 push_result（位于结果列表更「旧」的尾端），
    等待方先消费到真实结果，这里的补偿结果不会造成重复执行。
    """
    try:
        push_result(client, job_id, {}, error=error)
    except Exception:
        pass


def data_root() -> str:
    return os.getenv("CONTROL_PLANE_DATA_ROOT") or os.getcwd()
