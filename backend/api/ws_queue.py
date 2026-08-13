import asyncio
import threading
from backend.api.ws import broadcast_progress
from collections import deque

# Thread-safe message queue for broadcasting from worker threads
_message_queue = deque()
_queue_lock = threading.Lock()
_broadcast_task = None
_loop = None


def get_ws_callback():
    """Returns a sync callback that can be called from thread pool workers."""
    def callback(task_id, step_id, progress, message, extra=None):
        with _queue_lock:
            _message_queue.append((task_id, step_id, progress, message, extra or {}))
    return callback


async def _drain_queue():
    """Background task that drains the queue and broadcasts messages."""
    global _loop
    _loop = asyncio.get_event_loop()
    while True:
        try:
            messages = []
            with _queue_lock:
                while _message_queue:
                    messages.append(_message_queue.popleft())
            for task_id, step_id, progress, message, extra in messages:
                try:
                    await broadcast_progress(task_id, step_id, progress, message, extra)
                except Exception as e:
                    print(f"[ws_queue] broadcast error for {task_id}/{step_id}: {e}", flush=True)
        except Exception as e:
            print(f"[ws_queue] drainer error: {e}", flush=True)
        await asyncio.sleep(0.05)  # 50ms batch interval


def start_queue_drainer():
    """Start the background queue drainer. Call once at app startup."""
    global _broadcast_task
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            _broadcast_task = loop.create_task(_drain_queue())
    except RuntimeError:
        pass
