import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from backend.voiceforge.database import load_config, session
from backend.control_plane.celery_runtime import create_celery_app


try:
    from celery import Celery
    import redis
except ImportError:
    Celery = None
    redis = None


# ── 本地回退线程池（Celery Worker 不可用时使用）─────────────────────
# 容量随「配音谷并发上限」增长；实际在途数量由任务泵（pump_pending_tasks）控制。
_local_pool: Optional[ThreadPoolExecutor] = None
_local_pool_size = 0
_local_lock = threading.Lock()


def _get_local_pool() -> ThreadPoolExecutor:
    global _local_pool, _local_pool_size
    from backend.voiceforge.task_defaults import synthesis_concurrency

    desired = max(4, synthesis_concurrency())
    with _local_lock:
        if _local_pool is None or desired > _local_pool_size:
            _local_pool = ThreadPoolExecutor(max_workers=desired, thread_name_prefix="vf-local")
            _local_pool_size = desired
        return _local_pool


def celery_available():
    if Celery is None or redis is None:
        return False
    config = load_config()
    try:
        redis.Redis.from_url(os.getenv("VOICEFORGE_REDIS_URL", config["redis_url"]), socket_connect_timeout=1, socket_timeout=1).ping()
        return True
    except redis.RedisError:
        return False


def celery_worker_available():
    if not celery_available() or Celery is None:
        return False
    try:
        return bool(celery_app.control.ping(timeout=0.5))
    except Exception:
        return False


def queue_mode() -> str:
    """当前任务投递模式：celery=走 Celery 队列；local=Worker 不可用，由本地线程池回退。"""
    return "celery" if celery_worker_available() else "local"


def _run_task(task_id: str):
    from backend.voiceforge.database import session as db_session
    from backend.voiceforge.services import export_project_srt, export_sentence_archive, merge_project_audio, synthesize_sentence, synthesize_voice_emotion

    with db_session() as conn:
        task = conn.execute("SELECT task_type, input_json FROM vf_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return
    import json
    payload = json.loads(task["input_json"])
    if task["task_type"] == "synthesize_sentence":
        synthesize_sentence(payload["sentence_id"], task_id, payload.get("sentence_version"), payload.get("interface_id"))
    elif task["task_type"] == "merge_project_audio":
        merge_project_audio(payload["project_id"], task_id, payload.get("chapter_id"), payload.get("format", "wav"), payload.get("gap_seconds", 0))
    elif task["task_type"] == "export_srt":
        export_project_srt(payload["project_id"], task_id, payload.get("chapter_id"))
    elif task["task_type"] == "export_sentence_archive":
        export_sentence_archive(payload["project_id"], task_id, payload.get("chapter_id"))
    elif task["task_type"] == "synthesize_voice_emotion":
        synthesize_voice_emotion(payload["voice_id"], payload["emotion"], payload["text"], payload["instruct"], payload["interface_id"], task_id)
    else:
        from backend.voiceforge.services import update_task
        update_task(task_id, "failed", 1, error_message=f"不支持的任务类型: {task['task_type']}")


def _task_settled(task_id: str) -> bool:
    """任务是否已被业务层写入终态（失败/取消/成功）。

    已写入终态说明失败是业务结果（如 TTS 持续报错），不应再触发 Celery 级重试，
    避免重复消耗 TTS 额度。
    """
    try:
        with session() as conn:
            row = conn.execute("SELECT status FROM vf_tasks WHERE id = ?", (task_id,)).fetchone()
        return bool(row and row["status"] in {"failed", "cancelled", "succeeded"})
    except Exception:
        return False


def dispatch(task_id: str, queue: str = "synthesis") -> Optional[str]:
    """把任务发送到 Celery，返回 celery task id；Worker 不可用时返回 None。"""
    if not celery_worker_available():
        return None
    config = load_config()
    app = Celery(
        "voiceforge",
        broker=os.getenv("VOICEFORGE_REDIS_URL", config["redis_url"]),
        backend=os.getenv("VOICEFORGE_CELERY_RESULT_URL", config["celery_result_url"]),
    )
    result = app.send_task("backend.voiceforge.tasks.celery_app.run_task", args=[task_id], queue=config["queues"].get(queue, queue))
    return result.id


def _mark_dispatched(task_id: str, celery_task_id: str | None = None):
    with session() as conn:
        if celery_task_id:
            conn.execute("UPDATE vf_tasks SET celery_task_id = ?, dispatched = 1 WHERE id = ?", (celery_task_id, task_id))
        else:
            conn.execute("UPDATE vf_tasks SET dispatched = 1 WHERE id = ?", (task_id,))


def _run_local(task_id: str):
    try:
        _run_task(task_id)
    except Exception:
        # _run_task 内部已把任务写入终态，这里只防止异常外泄到线程池
        pass


def dispatch_task(task_id: str, queue: str = "synthesis") -> bool:
    """统一投递入口：优先 Celery，Worker 不可用时降级到本地线程池。

    返回值表示是否成功投递（任务泵按此统计在途数量）。
    """
    try:
        celery_task_id = dispatch(task_id, queue)
        if celery_task_id:
            _mark_dispatched(task_id, celery_task_id)
            return True
    except Exception:
        # 发送失败不视为致命错误，继续尝试本地回退
        pass
    try:
        _mark_dispatched(task_id)
        _get_local_pool().submit(_run_local, task_id)
        return True
    except Exception:
        try:
            with session() as conn:
                conn.execute("UPDATE vf_tasks SET dispatched = 0 WHERE id = ?", (task_id,))
        except Exception:
            pass
        return False


if Celery is not None:
    _config = load_config()
    celery_app = create_celery_app("voiceforge")

    @celery_app.task(name="backend.voiceforge.tasks.celery_app.run_task", bind=True, max_retries=1, default_retry_delay=5, acks_late=True)
    def run_task(self, task_id):
        try:
            _run_task(task_id)
        except Exception as exc:
            if _task_settled(task_id):
                # 业务层已记录失败：不再重试，避免重复调用 TTS
                return {"task_id": task_id, "status": "failed", "retried": False}
            raise self.retry(exc=exc)
        return {"task_id": task_id, "status": "ok"}
