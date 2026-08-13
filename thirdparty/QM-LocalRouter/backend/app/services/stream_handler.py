"""
SSE stream utilities for chunked response handling.
"""
import json
from typing import AsyncIterator


async def collect_stream_text(iterator: AsyncIterator[str]) -> str:
    """Collect all text content from an SSE stream into a single string."""
    parts = []
    async for chunk in iterator:
        if chunk.startswith("data: "):
            data_str = chunk[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    parts.append(content)
            except json.JSONDecodeError:
                pass
    return "".join(parts)


def format_sse_event(data: dict) -> str:
    """Format a dict as an SSE event string."""
    return f"data: {json.dumps(data)}\n\n"


def format_sse_error(message: str) -> str:
    """Format an error as an SSE event."""
    return format_sse_event({"error": {"message": message}})


def format_sse_done() -> str:
    """Format the [DONE] marker."""
    return "data: [DONE]\n\n"
