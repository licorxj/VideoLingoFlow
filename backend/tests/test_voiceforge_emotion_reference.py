"""Unit tests for ``_resolve_emotion_clone_reference`` in ``backend.voiceforge.services``.

This function picks a per-emotion reference audio (from a voice's ``emotions_json``)
to colour clone synthesis by the sentence's emotion tag, falling back to the voice's
primary reference audio when no match / the matched audio is missing.

The test stubs the heavy TTS/LLM submodules so the module imports without pulling in
third-party SDKs, then drives the pure resolver directly.

Run directly:
    python backend/tests/test_voiceforge_emotion_reference.py
Or via pytest:
    python -m pytest backend/tests/test_voiceforge_emotion_reference.py
"""
import os
import sys
import json
import types
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# Stub heavy submodules so importing services.py does not pull TTS/LLM SDKs.
_STUBS = {
    "backend.tts": types.ModuleType("backend.tts"),
    "backend.tts.tts_factory": types.ModuleType("backend.tts.tts_factory"),
    "backend.llm": types.ModuleType("backend.llm"),
    "backend.llm.llm_client": types.ModuleType("backend.llm.llm_client"),
    "backend.voiceforge.prompting": types.ModuleType("backend.voiceforge.prompting"),
}
_STUBS["backend.tts.tts_factory"].get_tts_engine = lambda *a, **k: None
_STUBS["backend.llm.llm_client"].LLMClient = object
for _name in ("PROMPT_SCRIPT_ANALYSIS", "assemble_prompt", "limit_source", "temperature_for"):
    setattr(_STUBS["backend.voiceforge.prompting"], _name, None)
sys.modules.update(_STUBS)

from backend.voiceforge import services as svc  # noqa: E402


class _FakeResolver:
    """resolve_storage_key stand-in: maps a storage key to a temp file whose
    existence is controlled per-key via ``exists_map``."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.exists_map: dict[str, bool] = {}

    def __call__(self, key: str) -> Path:
        path = self.tmp / (key.replace("/", "_") + ".wav")
        if self.exists_map.get(key, False):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00\x00")  # non-empty
        return path


def _data(mode="clone", emotions=None, emotion="happy", voice_id="v1"):
    return {
        "mode": mode,
        "emotion": emotion,
        "voice_id": voice_id,
        "emotions_json": json.dumps(emotions or []),
    }


def test_hit_existing_audio_returns_path_and_instruct(tmp_path):
    resolver = _FakeResolver(tmp_path)
    resolver.exists_map["voices/v1/emotions/happy.wav"] = True
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(
            _data(emotions=[{"name": "happy", "audio_path": "voices/v1/emotions/happy.wav", "instruct": "开心地"}]),
            "happy",
        )
    assert ref is not None and Path(ref).exists()
    assert instruct == "开心地"


def test_hit_missing_audio_falls_back_and_logs_warning(tmp_path):
    resolver = _FakeResolver(tmp_path)
    resolver.exists_map["voices/v1/emotions/happy.wav"] = False  # file absent
    with patch.object(svc, "resolve_storage_key", resolver):
        with patch.object(svc.logger, "warning") as warn:
            ref, instruct = svc._resolve_emotion_clone_reference(
                _data(emotions=[{"name": "happy", "audio_path": "voices/v1/emotions/happy.wav"}]),
                "happy",
                task_id="task-123",
            )
    assert ref is None and instruct == ""
    warn.assert_called_once()
    # signature: logger.warning(fmt, task_id, voice_id, emotion, audio_key)
    assert warn.call_args.args[1] == "task-123"


def test_no_name_match_falls_back(tmp_path):
    resolver = _FakeResolver(tmp_path)
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(
            _data(emotion="angry", emotions=[{"name": "happy", "audio_path": "voices/v1/emotions/happy.wav"}]),
            "angry",
        )
    assert ref is None and instruct == ""
    # resolver must never have been asked for a path on a non-matching entry
    assert resolver.exists_map == {}


def test_non_clone_mode_never_matches(tmp_path):
    resolver = _FakeResolver(tmp_path)
    resolver.exists_map["voices/v1/emotions/happy.wav"] = True
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(
            _data(mode="preset_voice", emotions=[{"name": "happy", "audio_path": "voices/v1/emotions/happy.wav"}]),
            "happy",
        )
    assert ref is None and instruct == ""


def test_empty_emotion_falls_back(tmp_path):
    resolver = _FakeResolver(tmp_path)
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(
            _data(emotion="", emotions=[{"name": "happy", "audio_path": "voices/v1/emotions/happy.wav"}]),
            "",
        )
    assert ref is None and instruct == ""


def test_case_insensitive_and_whitespace_normalized(tmp_path):
    resolver = _FakeResolver(tmp_path)
    resolver.exists_map["voices/v1/emotions/happy.wav"] = True
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(
            _data(emotions=[{"name": "happy", "audio_path": "voices/v1/emotions/happy.wav", "instruct": "x"}]),
            "  HAPPY  ",
        )
    assert ref is not None and Path(ref).exists()


def test_malformed_emotions_json_falls_back(tmp_path):
    resolver = _FakeResolver(tmp_path)
    data = _data(emotions=None)
    data["emotions_json"] = "not-json"
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(data, "happy")
    assert ref is None and instruct == ""


def test_reference_storage_key_fallback_when_audio_path_absent(tmp_path):
    resolver = _FakeResolver(tmp_path)
    resolver.exists_map["voices/v1/ref.wav"] = True
    with patch.object(svc, "resolve_storage_key", resolver):
        ref, instruct = svc._resolve_emotion_clone_reference(
            _data(emotions=[{"name": "happy", "reference_storage_key": "voices/v1/ref.wav", "instruct": "y"}]),
            "happy",
        )
    assert ref is not None and Path(ref).exists()


def _run_all():
    import tempfile

    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    with tempfile.TemporaryDirectory() as td:
        for fn in funcs:
            # isolated temp dir per test to avoid files left by earlier tests
            fn(Path(td) / fn.__name__)
            print(f"  [OK] {fn.__name__}")
            passed += 1
    print(f"\nAll {passed} tests passed.")


if __name__ == "__main__":
    _run_all()
