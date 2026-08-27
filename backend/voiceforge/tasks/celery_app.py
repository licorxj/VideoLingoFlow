import os

from backend.voiceforge.database import load_config
from backend.control_plane.celery_runtime import create_celery_app


try:
    from celery import Celery
    import redis
except ImportError:
    Celery = None
    redis = None


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


def _run_task(task_id: str):
    from backend.voiceforge.database import session
    from backend.voiceforge.services import export_project_srt, export_sentence_archive, merge_project_audio, synthesize_sentence, synthesize_voice_emotion

    with session() as conn:
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


def dispatch(task_id: str, queue: str = "synthesis"):
    if not celery_worker_available():
        raise RuntimeError("Celery worker is unavailable")
    config = load_config()
    app = Celery(
        "voiceforge",
        broker=os.getenv("VOICEFORGE_REDIS_URL", config["redis_url"]),
        backend=os.getenv("VOICEFORGE_CELERY_RESULT_URL", config["celery_result_url"]),
    )
    result = app.send_task("backend.voiceforge.tasks.celery_app.run_task", args=[task_id], queue=config["queues"].get(queue, queue))
    return result.id


if Celery is not None:
    _config = load_config()
    celery_app = create_celery_app("voiceforge")

    @celery_app.task(name="backend.voiceforge.tasks.celery_app.run_task")
    def run_task(task_id):
        _run_task(task_id)
