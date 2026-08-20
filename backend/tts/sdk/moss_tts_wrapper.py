import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[3] / "_model_cache" / "MOSS-TTS-Nano-ONNX"
_runtime = None
_runtime_lock = threading.Lock()


def _get_runtime(cpu_threads):
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            from backend.tts.sdk.moss_tts import OnnxTtsRuntime

            _runtime = OnnxTtsRuntime(
                model_dir=MODEL_DIR,
                thread_count=max(1, int(cpu_threads)),
                execution_provider="cpu",
            )
        return _runtime


def synthesize(
    text,
    output_path,
    voice=None,
    mode=None,
    ref_audio=None,
    speed=None,
    timeout=None,
    cpu_threads=4,
    max_new_frames=375,
    voice_clone_max_text_tokens=75,
    enable_wetext=False,
    enable_normalize_tts_text=True,
    seed=None,
    **kwargs,
):
    if mode in {"clone", "controllable_clone"} and not ref_audio:
        logger.error("mossTTS voice cloning requires ref_audio")
        return False
    try:
        runtime = _get_runtime(cpu_threads)
        with _runtime_lock:
            runtime.synthesize(
                text=text,
                voice=voice or "Junhao",
                prompt_audio_path=ref_audio,
                output_audio_path=output_path,
                sample_mode="fixed",
                do_sample=True,
                streaming=True,
                max_new_frames=int(max_new_frames),
                voice_clone_max_text_tokens=int(voice_clone_max_text_tokens),
                enable_wetext=bool(enable_wetext),
                enable_normalize_tts_text=bool(enable_normalize_tts_text),
                seed=seed,
            )
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except Exception:
        logger.exception("mossTTS synthesis failed")
        return False


def list_voices():
    return ["Junhao"]
