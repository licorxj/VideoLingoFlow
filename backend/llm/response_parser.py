"""
Response parser: handles LLM JSON response parsing with retry and validation.
"""
import json
import re
from typing import Any, Optional, Callable


def parse_json_response(content: str) -> Any:
    """Parse JSON from LLM response, with fallback repair."""
    if not content or not content.strip():
        return {"error": "Empty response"}

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try json_repair
    try:
        import json_repair
        return json_repair.loads(content)
    except Exception:
        pass

    # Try to extract JSON from markdown code blocks
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON object/array in the text
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    # Return raw content as fallback
    return content


def validate_response(
    data: Any,
    required_keys: Optional[list[str]] = None,
    validator: Optional[Callable] = None,
) -> dict:
    """
    Validate parsed LLM response.

    Args:
        data: Parsed response data.
        required_keys: List of keys that must be present (for dict responses).
        validator: Custom validator function.

    Returns:
        {"status": "success"|"error", "message": str, "data": Any}
    """
    if isinstance(data, dict) and "error" in data:
        return {"status": "error", "message": data["error"], "data": data}

    if validator:
        return validator(data)

    if required_keys and isinstance(data, dict):
        missing = [k for k in required_keys if k not in data]
        if missing:
            return {
                "status": "error",
                "message": f"Missing required keys: {missing}",
                "data": data,
            }

    return {"status": "success", "message": "OK", "data": data}


def extract_subtitles(data: Any) -> list[dict]:
    """Extract subtitle entries from various LLM response formats."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["subtitles", "segments", "sentences", "lines", "result"]:
            if key in data and isinstance(data[key], list):
                return data[key]
    return []
