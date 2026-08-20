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
    """服务是否可用：Redis 可 ping 且 manager 心跳键新鲜。"""
    try:
        rc = client or get_redis()
        if not rc.ping():
            return False
        raw = rc.get(config.status_key())
        if not raw:
            return False
        info = json.loads(raw)
        return (_now() - float(info.get("ts", 0))) <= config.heartbeat_ttl() * 2
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
                events = client.lrange(pkey, 0, -1)
            except Exception:
                events = []
            forward = False
            for raw in events[prog_idx:]:
                try:
                    ev = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                prog_idx += 1
                pct = ev.get("pct", last_pct)
                msg = ev.get("msg", "")
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


def data_root() -> str:
    return os.getenv("CONTROL_PLANE_DATA_ROOT") or os.getcwd()
