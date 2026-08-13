import os
from functools import wraps

from backend.control_plane.runtime import TaskCancelledError, TaskTimeoutError, classify_error, queue_for


try:
    from celery import Celery
except ImportError:
    Celery = None


def celery_config() -> dict:
    return {
        "broker": os.getenv("CONTROL_PLANE_CELERY_BROKER_URL") or os.getenv("VOICEFORGE_REDIS_URL", "redis://127.0.0.1:6379/2"),
        "backend": os.getenv("CONTROL_PLANE_CELERY_RESULT_URL") or os.getenv("VOICEFORGE_CELERY_RESULT_URL", "redis://127.0.0.1:6379/3"),
        "queues": {resource: queue_for(resource) for resource in ("cpu", "gpu", "llm", "tts", "io")},
    }


def create_celery_app(name: str = "videolingo"):
    if Celery is None:
        return None
    config = celery_config()
    app = Celery(name, broker=config["broker"], backend=config["backend"])
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        imports=("backend.control_plane.workflow_runtime",),
        task_routes={"*": {"queue": config["queues"]["io"]}},
        task_default_retry_delay=5,
        task_time_limit=int(os.getenv("CELERY_HARD_TIMEOUT", "3600")),
        task_soft_time_limit=int(os.getenv("CELERY_SOFT_TIMEOUT", "3300")),
    )
    return app


celery_app = create_celery_app()


def unified_task(app, *, resource: str = "io", timeout: int | None = None, max_retries: int = 3):
    def decorator(func):
        if app is None:
            return func

        @app.task(bind=True, autoretry_for=(), max_retries=max_retries, soft_time_limit=timeout, time_limit=timeout + 30 if timeout else None, queue=queue_for(resource))
        @wraps(func)
        def execute(self, task_id, *args, **kwargs):
            try:
                return func(task_id, *args, **kwargs)
            except (TaskCancelledError, TaskTimeoutError):
                raise
            except Exception as exc:
                if classify_error(exc) == "retryable" and self.request.retries < max_retries:
                    raise self.retry(exc=exc, countdown=min(60, 2 ** self.request.retries))
                raise

        return execute
    return decorator
