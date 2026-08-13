import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class PiSessionStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("CREATE TABLE IF NOT EXISTS pi_sessions (project_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, cwd TEXT NOT NULL, session_dir TEXT NOT NULL, created_at REAL NOT NULL, last_activity REAL NOT NULL, message_count INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0, messages_json TEXT NOT NULL DEFAULT '[]')")
            db.execute("CREATE TABLE IF NOT EXISTS pi_session_history (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, session_id TEXT NOT NULL, cwd TEXT NOT NULL DEFAULT '', session_dir TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, closed_at REAL NOT NULL, message_count INTEGER NOT NULL DEFAULT 0, messages_json TEXT NOT NULL DEFAULT '[]')")
            db.execute("CREATE TABLE IF NOT EXISTS pi_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS pi_assistants (assistant_id TEXT PRIMARY KEY, config_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS pi_integrations (kind TEXT NOT NULL, item_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(kind, item_id))")
            columns = {row[1] for row in db.execute("PRAGMA table_info(pi_session_history)")}
            if "cwd" not in columns:
                db.execute("ALTER TABLE pi_session_history ADD COLUMN cwd TEXT NOT NULL DEFAULT ''")
            if "session_dir" not in columns:
                db.execute("ALTER TABLE pi_session_history ADD COLUMN session_dir TEXT NOT NULL DEFAULT ''")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def get(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT project_id, session_id, cwd, session_dir, created_at, last_activity, message_count, closed, messages_json FROM pi_sessions WHERE project_id = ?", (project_id,)).fetchone()
        if not row:
            return None
        return {"project_id": row[0], "session_id": row[1], "cwd": row[2], "session_dir": row[3], "created_at": row[4], "last_activity": row[5], "message_count": row[6], "closed": bool(row[7]), "messages": json.loads(row[8] or "[]")}

    def upsert(self, project_id: str, session_id: str, cwd: str, session_dir: str, created_at: float, last_activity: float, message_count: int, closed: bool = False, messages: list[dict[str, Any]] | None = None) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO pi_sessions (project_id, session_id, cwd, session_dir, created_at, last_activity, message_count, closed, messages_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET session_id=excluded.session_id, cwd=excluded.cwd, session_dir=excluded.session_dir, created_at=excluded.created_at, last_activity=excluded.last_activity, message_count=excluded.message_count, closed=excluded.closed, messages_json=excluded.messages_json", (project_id, session_id, cwd, session_dir, created_at, last_activity, message_count, int(closed), json.dumps(messages or [], ensure_ascii=False)))

    def mark_closed(self, project_id: str) -> None:
        with self._connect() as db:
            row = db.execute("SELECT session_id, created_at, message_count, messages_json FROM pi_sessions WHERE project_id = ?", (project_id,)).fetchone()
            if row and not db.execute("SELECT 1 FROM pi_session_history WHERE session_id = ? AND closed_at >= ?", (row[0], time.time() - 2)).fetchone():
                current = db.execute("SELECT cwd, session_dir FROM pi_sessions WHERE project_id = ?", (project_id,)).fetchone()
                db.execute("INSERT INTO pi_session_history (project_id, session_id, cwd, session_dir, created_at, closed_at, message_count, messages_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (project_id, row[0], current[0], current[1], row[1], time.time(), row[2], row[3]))
            db.execute("UPDATE pi_sessions SET closed = 1, last_activity = ? WHERE project_id = ?", (time.time(), project_id))

    def clear_messages(self, project_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE pi_sessions SET messages_json = '[]', message_count = 0, last_activity = ? WHERE project_id = ?", (time.time(), project_id))

    def history(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT id, session_id, cwd, session_dir, created_at, closed_at, message_count, messages_json FROM pi_session_history WHERE project_id = ? ORDER BY closed_at DESC LIMIT 30", (project_id,)).fetchall()
        return [{"id": row[0], "session_id": row[1], "cwd": row[2], "session_dir": row[3], "created_at": row[4], "closed_at": row[5], "message_count": row[6], "messages": json.loads(row[7] or "[]")} for row in rows]

    def delete_history(self, project_id: str, history_id: int) -> bool:
        """删除指定历史会话记录，返回是否删除成功。"""
        with self._connect() as db:
            cursor = db.execute("DELETE FROM pi_session_history WHERE id = ? AND project_id = ?", (history_id, project_id))
        return cursor.rowcount > 0

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute("SELECT key, value_json FROM pi_settings").fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}

    def set_setting(self, key: str, value: Any) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO pi_settings (key, value_json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value, ensure_ascii=False)))

    def assistants(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute("SELECT assistant_id, config_json FROM pi_assistants").fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}

    def set_assistant(self, assistant_id: str, value: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO pi_assistants (assistant_id, config_json) VALUES (?, ?) ON CONFLICT(assistant_id) DO UPDATE SET config_json=excluded.config_json", (assistant_id, json.dumps(value, ensure_ascii=False)))

    def integrations(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if kind:
                rows = db.execute("SELECT kind, item_id, name, path, enabled FROM pi_integrations WHERE kind = ? ORDER BY name", (kind,)).fetchall()
            else:
                rows = db.execute("SELECT kind, item_id, name, path, enabled FROM pi_integrations ORDER BY kind, name").fetchall()
        return [{"kind": row[0], "item_id": row[1], "name": row[2], "path": row[3], "enabled": bool(row[4])} for row in rows]

    def replace_integrations(self, kind: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.execute("DELETE FROM pi_integrations WHERE kind = ?", (kind,))
            for item in items:
                db.execute("INSERT INTO pi_integrations (kind, item_id, name, path, enabled) VALUES (?, ?, ?, ?, ?)", (kind, item["item_id"], item["name"], item["path"], int(item.get("enabled", False))))
        return self.integrations(kind)

    def set_integration(self, kind: str, item_id: str, enabled: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE pi_integrations SET enabled = ? WHERE kind = ? AND item_id = ?", (int(enabled), kind, item_id))
