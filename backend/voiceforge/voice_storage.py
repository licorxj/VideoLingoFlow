import json
import shutil
from pathlib import Path

from backend.voiceforge.database import session
from backend.voiceforge.storage import resolve_storage_key


def voice_directory_key(voice_id: str):
    return f"voices/{voice_id}"


def write_voice_config(voice_id: str):
    with session() as conn:
        row = conn.execute("SELECT * FROM vf_voices WHERE id = ?", (voice_id,)).fetchone()
    if not row:
        return
    voice = dict(row)
    tags = _json_value(voice.get("tags_json"), [])
    legacy_params = _json_value(voice.get("legacy_params_json"), {})
    params = legacy_params or _json_value(voice.get("params_json"), {})
    emotions = _json_value(voice.get("emotions_json"), [])
    config = {
        "name": voice["name"],
        "display_name": voice["display_name"],
        "engine": voice.get("legacy_engine") or voice.get("interface_id") or "",
        "voice_key": voice.get("legacy_voice_key") or voice.get("voice_id") or "",
        "gender": voice.get("gender") or "",
        "age": voice.get("voice_age") or "",
        "pitch": voice.get("voice_pitch") or "",
        "dialect": voice.get("dialect") or "普通话",
        "language": voice.get("language") or "zh-CN",
        "tags": tags,
        "description": voice.get("description") or "",
        "is_cloned": bool(voice.get("is_cloned")),
        "is_builtin": bool(voice.get("is_builtin")),
        "design_text": voice.get("design_text") or "",
        "design_params": params,
        "preview_text": voice.get("preview_text") or "",
        "emotions": emotions,
        "voice_group": voice.get("voice_group") or "",
        "sample_path": voice.get("sample_storage_key") or voice.get("reference_storage_key") or "",
        "embedding_path": voice.get("embedding_storage_key") or "",
    }
    directory = resolve_storage_key(voice_directory_key(voice_id))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "voice_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_voice_directory(voice_id: str):
    shutil.rmtree(resolve_storage_key(voice_directory_key(voice_id)), ignore_errors=True)


def materialize_voice_sample(voice_id: str, source_key: str | None):
    if not source_key:
        return None
    source = resolve_storage_key(source_key)
    if not source.exists():
        return None
    suffix = source.suffix.lower() or ".wav"
    key = f"{voice_directory_key(voice_id)}/design{suffix}"
    destination = resolve_storage_key(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return key


def _json_value(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback
