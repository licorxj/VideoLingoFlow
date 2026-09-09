"""运行时系统通知：轻量文件存储 + 查询。

供工作流节点（如「推送到剪辑台」）发起系统提醒通知，
前端头部通知中心（useHeaderInbox）通过 /api/notifications 轮询拉取。
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

NOTIFICATIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "runtime_notifications.json"
_LOCK = threading.Lock()
MAX_ITEMS = 500
ALLOWED_KINDS = {"info", "success", "error"}


def _read() -> list[dict]:
    try:
        with open(NOTIFICATIONS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("notifications"), list):
            return data["notifications"]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def push_notification(
    kind: str,
    title: str,
    description: str,
    task_id: str = "",
    link: str = "",
) -> dict:
    """追加一条系统通知（原子写入，超出上限裁剪最旧条目）。"""
    item = {
        "id": f"ntf_{uuid.uuid4().hex[:12]}",
        "kind": kind if kind in ALLOWED_KINDS else "info",
        "title": str(title or "系统通知"),
        "description": str(description or ""),
        "task_id": str(task_id or ""),
        "link": str(link or ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _LOCK:
        NOTIFICATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        items = _read()
        items.insert(0, item)
        temporary = NOTIFICATIONS_PATH.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"notifications": items[:MAX_ITEMS]}, handle, ensure_ascii=False, indent=2)
        temporary.replace(NOTIFICATIONS_PATH)
    return item


def list_notifications(since: str = "", limit: int = 50) -> tuple[list[dict], str]:
    """返回通知列表（created_at 晚于 since 的条目，ISO 字符串比较）与服务器当前时间。"""
    items = _read()
    if since:
        items = [item for item in items if str(item.get("created_at", "")) > str(since)]
    server_time = datetime.now(timezone.utc).isoformat()
    return items[: max(1, int(limit))], server_time
