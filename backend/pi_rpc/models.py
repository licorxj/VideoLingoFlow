from dataclasses import dataclass, field
from typing import Any


@dataclass
class PiSessionInfo:
    session_id: str
    project_id: str
    cwd: str
    model: str
    tools: list[str]
    created_at: float
    last_activity: float
    streaming: bool = False
    message_count: int = 0
    last_error: str | None = None
    closed: bool = False
    seq: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "model": self.model,
            "tools": self.tools,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "streaming": self.streaming,
            "message_count": self.message_count,
            "last_error": self.last_error,
            "closed": self.closed,
            "seq": self.seq,
            "messages": self.messages,
        }
