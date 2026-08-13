"""ASR factory: creates ASR engine instances by name."""
from typing import Optional, Dict, Any
from backend.asr.asr_base import ASRBase
from backend.asr.asr_whisperx import WhisperXLocal

_ENGINES = {}

def _load_engines():
    global _ENGINES
    if _ENGINES:
        return
    _ENGINES = {
        "whisperx_local": WhisperXLocal(),
    }
    try:
        from backend.asr.asr_qwen3_asr import Qwen3ASRLocal
        _ENGINES["qwen3_asr"] = Qwen3ASRLocal()
    except ImportError:
        pass
    try:
        from backend.asr.asr_elevenlabs import ElevenLabsASRLocal
        _ENGINES["elevenlabs"] = ElevenLabsASRLocal()
    except ImportError:
        pass
    try:
        from backend.asr.asr_mimo import MiMoASRLocal
        _ENGINES["mimo_asr"] = MiMoASRLocal()
    except ImportError:
        pass
    try:
        from backend.asr.asr_funasr_nano import FunASRNanoLocal
        _ENGINES["funasr_nano"] = FunASRNanoLocal()
    except ImportError:
        pass
    try:
        from backend.asr.asr_whisper_302 import WhisperX302
        _ENGINES["whisper_302"] = WhisperX302()
    except ImportError:
        pass

def get_asr_engine(name: str) -> ASRBase:
    _load_engines()
    engine = _ENGINES.get(name)
    if engine is None:
        print(f"Unknown ASR engine: {name}, falling back to whisperx_local")
        engine = _ENGINES["whisperx_local"]
    return engine

def run_asr(
    input_path: str, output_path: str, callback=None,
    *, engine_name=None, interface_id=None,
    model=None, language=None, **extra_kwargs,
) -> dict:
    engine_name = engine_name or "whisperx_local"
    engine = get_asr_engine(engine_name)
    return engine.transcribe(
        input_path, output_path,
        callback=callback, model=model, language=language,
        **extra_kwargs,
    )

def run_asr_with_post_processing(
    input_path: str, 
    output_path: str, 
    callback=None,
    *,
    engine_name: str = "whisperx_local",
    model: str = None,
    language: str = None,
    vad_engine: Optional[str] = None,
    alignment_engine: Optional[str] = None,
    diarize_engine: Optional[str] = None,
    vad_options: Optional[Dict[str, Any]] = None,
    alignment_options: Optional[Dict[str, Any]] = None,
    diarize_options: Optional[Dict[str, Any]] = None,
    **extra_kwargs,
) -> dict:
    """Run ASR with optional post-processing (VAD, alignment, and/or speaker diarization).

    This function enables hybrid processing pipelines where you can:
    1. Use any ASR engine for transcription
    2. Apply VAD from a different engine (e.g., use FunASR's VAD with WhisperX)
    3. Apply word-level alignment from another engine (e.g., use WhisperX alignment with MiMo ASR)
    4. Apply speaker diarization from another engine (e.g., use pyannote with Qwen3-ASR)

    Parameters
    ----------
    input_path : str
        Path to audio/video file.
    output_path : str
        Path to write JSON result.
    callback : callable, optional
        Progress callback (percent: int, message: str).
    engine_name : str
        ASR engine name (default: "whisperx_local").
    model : str, optional
        Model name for the ASR engine.
    language : str, optional
        Language code for the ASR engine.
    vad_engine : str, optional
        VAD engine name for post-processing (e.g., "silero", "fsmn", "webrtc").
    alignment_engine : str, optional
        Alignment engine name for post-processing (e.g., "whisperx", "qwen3").
    diarize_engine : str, optional
        Diarization engine name for post-processing (e.g., "pyannote", "cam++").
    vad_options : dict, optional
        VAD-specific options.
    alignment_options : dict, optional
        Alignment-specific options.
    diarize_options : dict, optional
        Diarization-specific options.
    **extra_kwargs
        Extra arguments passed to the ASR engine.

    Returns
    -------
    dict
        ASR result with optional VAD, word timestamps, and speaker diarization applied.

    Examples
    --------
    # Use Qwen3-ASR with FunASR's VAD and pyannote diarization
    result = run_asr_with_post_processing(
        "audio.wav", "output.json",
        engine_name="qwen3_asr",
        vad_engine="fsmn",
        diarize_engine="pyannote"
    )
    
    # Use MiMo ASR with WhisperX alignment for word timestamps
    result = run_asr_with_post_processing(
        "audio.wav", "output.json",
        engine_name="mimo_asr",
        alignment_engine="whisperx"
    )
    """
    # Step 1: Run ASR
    if callback:
        callback(10, f"Running ASR with {engine_name}...")
    
    engine_name = engine_name or "whisperx_local"
    engine = get_asr_engine(engine_name)
    
    # Run ASR transcription
    asr_result = engine.transcribe(
        input_path, output_path,
        callback=callback, model=model, language=language,
        **extra_kwargs,
    )
    
    # Step 2: Apply post-processing if requested
    if vad_engine or alignment_engine or diarize_engine:
        if callback:
            callback(40, "Starting post-processing...")
        
        # Use the engine's post_process method
        asr_result = engine.post_process(
            asr_result=asr_result,
            audio_path=input_path,
            vad_engine=vad_engine,
            alignment_engine=alignment_engine,
            diarize_engine=diarize_engine,
            vad_options=vad_options,
            alignment_options=alignment_options,
            diarize_options=diarize_options,
            callback=callback,
        )
        
        # Save the post-processed result
        import json
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(asr_result, f, ensure_ascii=False, indent=2)
    
    return asr_result

def apply_post_processing(
    asr_result: dict,
    audio_path: str,
    callback=None,
    *,
    language: Optional[str] = None,
    vad_engine: Optional[str] = None,
    alignment_engine: Optional[str] = None,
    diarize_engine: Optional[str] = None,
    vad_options: Optional[Dict[str, Any]] = None,
    alignment_options: Optional[Dict[str, Any]] = None,
    diarize_options: Optional[Dict[str, Any]] = None,
    alignment_audio_path: Optional[str] = None,
) -> dict:
    """Apply post-processing to an existing ASR result.

    This function applies VAD, word-level alignment, and/or speaker diarization
    to an existing ASR result without re-running the ASR engine.

    Parameters
    ----------
    asr_result : dict
        Existing ASR result from any engine.
    audio_path : str
        Path to the original audio file.
    callback : callable, optional
        Progress callback (percent: int, message: str).
    language : str, optional
        Language code (e.g., "zh", "en"). If not provided, will try to extract from asr_result.
    vad_engine : str, optional
        VAD engine name (e.g., "silero", "fsmn", "webrtc").
    alignment_engine : str, optional
        Alignment engine name (e.g., "whisperx", "qwen3").
    diarize_engine : str, optional
        Diarization engine name (e.g., "pyannote", "cam++").
    vad_options : dict, optional
        VAD-specific options.
    alignment_options : dict, optional
        Alignment-specific options.
    diarize_options : dict, optional
        Diarization-specific options.
    alignment_audio_path : str, optional
        Path to audio file specifically for alignment (e.g., vocal-separated audio).
        If provided, this audio will be used for word-level alignment instead of the original audio.

    Returns
    -------
    dict
        Post-processed ASR result.
    """
    from backend.asr.asr_base import ASRBase

    # Get language from ASR result if not provided
    if language is None:
        language = asr_result.get("language", "auto")
        print(f"[PostProcess] Using language from ASR result: {language}")

    # Create a temporary base instance to use post_process method
    class TempASR(ASRBase):
        def transcribe(self, input_path, output_path, callback=None, **kwargs):
            return {}

    temp_engine = TempASR()

    if callback:
        callback(50, "Applying post-processing...")

    result = temp_engine.post_process(
        asr_result=asr_result,
        audio_path=audio_path,
        language=language,
        vad_engine=vad_engine,
        alignment_engine=alignment_engine,
        diarize_engine=diarize_engine,
        vad_options=vad_options,
        alignment_options=alignment_options,
        diarize_options=diarize_options,
        callback=callback,
        alignment_audio_path=alignment_audio_path,
    )

    return result

def list_asr_engines() -> list:
    _load_engines()
    return list(_ENGINES.keys())

def list_vad_engines() -> list:
    """List available VAD engines."""
    return ["silero", "fsmn", "webrtc"]

def list_alignment_engines() -> list:
    """List available word-level alignment engines."""
    return ["whisperx", "qwen3"]

def list_diarize_engines() -> list:
    """List available speaker diarization engines."""
    return ["pyannote", "cam++"]