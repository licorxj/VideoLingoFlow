"""ASR factory: creates ASR engine instances by name.

引擎生命周期：空闲超过 5 秒无任务调用时自动卸载（模型多在 transcribe 内以局部
变量使用、调用结束已释放，此处主要归还 torch 显存缓存），下次调用按需重建。
"""
from typing import Optional, Dict, Any
from backend.asr.asr_base import ASRBase
from backend.asr.asr_whisperx import WhisperXLocal
from backend.utils.engine_lifecycle import IdleEngineRegistry, release_gpu_cache

_ENGINES = {}
_REGISTRY = IdleEngineRegistry(idle_timeout=5.0, name="ASR")


def _asr_unloader(_engine):
    """ASR 引擎卸载：归还 torch 显存缓存并触发 GC。"""
    release_gpu_cache()

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
    return _REGISTRY.acquire(name, lambda: engine, unloader=_asr_unloader)

def run_asr(
    input_path: str, output_path: str, callback=None,
    *, engine_name=None, interface_id=None,
    model=None, language=None, **extra_kwargs,
) -> dict:
    engine_name = engine_name or "whisperx_local"
    # GPU 服务层：启用且服务可用时，把转录任务提交到常驻服务执行（模型复用 + 显存调度）
    try:
        from backend.gpu_service import client as gpu_client
        if gpu_client.gpu_service_enabled():
            return gpu_client.run_asr(
                engine_name, input_path, output_path,
                model=model, language=language,
                engine_params=extra_kwargs, callback=callback,
            )
    except Exception as exc:
        from backend.gpu_service.jobs import GpuServiceUnavailableError
        if not isinstance(exc, GpuServiceUnavailableError):
            print(f"[ASR] GPU 服务调用失败，回退进程内执行: {exc}")
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
        Alignment engine name for post-processing (e.g., "whisperx", "qwen3", "funasr").
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

# ---------------------------------------------------------------------------
# 分阶段后处理 API：VAD断句 / 时间戳对齐 / 说话人识别 / 标点恢复 可单独执行，
# 也可通过 run_post_process_pipeline 按固定顺序（VAD→对齐→说话人→标点）编排。
# ---------------------------------------------------------------------------

_POST_PROCESS_STAGE_ORDER = ("vad", "alignment", "diarization", "punctuation")
_STAGE_DEFAULT_ENGINES = {"vad": "fsmn", "alignment": "whisperx", "diarization": "diarize", "punctuation": "ct_punc"}


def _make_temp_engine() -> ASRBase:
    """构造一个无转录能力的 ASRBase 实例，仅用于复用其后处理方法。"""
    class _TempASR(ASRBase):
        def transcribe(self, input_path, output_path, callback=None, **kwargs):
            return {}

    return _TempASR()


def run_vad(
    asr_result: dict,
    audio_path: str,
    *,
    engine: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    callback=None,
) -> dict:
    """单独执行 VAD 断句阶段（引擎失败时按 fsmn → webrtc 链回退）。"""
    engine = engine or _STAGE_DEFAULT_ENGINES["vad"]
    if callback:
        callback(0, f"Running VAD with {engine}...")
    result = _make_temp_engine()._apply_vad(
        asr_result.copy(), audio_path, engine, options or {}
    )
    if callback:
        callback(100, "VAD completed")
    return result


def run_alignment(
    asr_result: dict,
    audio_path: str,
    *,
    engine: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    callback=None,
) -> dict:
    """单独执行词级时间戳对齐阶段。"""
    engine = engine or _STAGE_DEFAULT_ENGINES["alignment"]
    if language is None:
        language = asr_result.get("language", "auto")
    if callback:
        callback(0, f"Applying word alignment with {engine}...")
    result = _make_temp_engine()._apply_alignment(
        asr_result.copy(), audio_path, engine, options or {}, language
    )
    if callback:
        callback(100, "Alignment completed")
    return result


def run_diarization(
    asr_result: dict,
    audio_path: str,
    *,
    engine: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    callback=None,
) -> dict:
    """单独执行说话人识别阶段。"""
    engine = engine or _STAGE_DEFAULT_ENGINES["diarization"]
    if callback:
        callback(0, f"Applying speaker diarization with {engine}...")
    result = _make_temp_engine()._apply_diarization(
        asr_result.copy(), audio_path, engine, options or {}
    )
    if callback:
        callback(100, "Diarization completed")
    return result


def run_punctuation(
    asr_result: dict,
    *,
    engine: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    callback=None,
) -> dict:
    """单独执行标点恢复阶段（纯文本处理，无需音频）。"""
    engine = engine or _STAGE_DEFAULT_ENGINES["punctuation"]
    if callback:
        callback(0, f"Restoring punctuation with {engine}...")
    result = _make_temp_engine()._apply_punctuation(
        asr_result.copy(), engine, options or {}, language
    )
    if callback:
        callback(100, "Punctuation restoration completed")
    return result


def run_post_process_pipeline(
    asr_result: dict,
    audio_path: str,
    *,
    stages: Optional[list] = None,
    vad_engine: Optional[str] = None,
    alignment_engine: Optional[str] = None,
    diarize_engine: Optional[str] = None,
    vad_options: Optional[Dict[str, Any]] = None,
    alignment_options: Optional[Dict[str, Any]] = None,
    diarize_options: Optional[Dict[str, Any]] = None,
    punctuation_engine: Optional[str] = None,
    punctuation_options: Optional[Dict[str, Any]] = None,
    alignment_audio_path: Optional[str] = None,
    language: Optional[str] = None,
    callback=None,
) -> dict:
    """按固定顺序（VAD → 时间戳对齐 → 说话人识别 → 标点恢复）编排后处理流水线。

    Parameters
    ----------
    stages : list, optional
        要执行的阶段列表（"vad"/"alignment"/"diarization"/"punctuation"），顺序无关，
        内部始终按 VAD→对齐→说话人→标点 执行。为 None 时执行所有指定了引擎的阶段。
    各引擎参数 : str, optional
        阶段引擎名；stages 中列出但未指定引擎的阶段使用内置默认引擎。
    alignment_audio_path : str, optional
        词级对齐专用音源（如人声分离音频），缺省用 audio_path。
    language : str, optional
        对齐用语言码；缺省取 asr_result 中的 language。

    每个阶段独立容错：单阶段失败仅记录日志，不阻塞后续阶段。
    """
    engines = {
        "vad": vad_engine,
        "alignment": alignment_engine,
        "diarization": diarize_engine,
        "punctuation": punctuation_engine,
    }
    if stages is None:
        run_stages = [s for s in _POST_PROCESS_STAGE_ORDER if engines.get(s)]
    else:
        wanted = {str(s).lower() for s in stages}
        run_stages = [s for s in _POST_PROCESS_STAGE_ORDER if s in wanted]

    if not run_stages:
        return asr_result

    if language is None:
        language = asr_result.get("language", "auto")

    result = asr_result.copy()
    # 各阶段进度窗口：vad [0,35) / alignment [35,65) / diarization [65,90) / punctuation [90,100]
    windows = {"vad": (0, 35), "alignment": (35, 65), "diarization": (65, 90), "punctuation": (90, 100)}

    def _stage_cb(stage):
        if not callback:
            return None
        lo, hi = windows[stage]
        return lambda pct, msg: callback(lo + int(pct * (hi - lo) / 100), msg)

    if "vad" in run_stages:
        engine = engines["vad"] or _STAGE_DEFAULT_ENGINES["vad"]
        try:
            result = run_vad(result, audio_path, engine=engine,
                             options=vad_options, callback=_stage_cb("vad"))
        except Exception as e:
            print(f"[PostProcess Pipeline] VAD failed ({engine}): {e}, continuing")

    if "alignment" in run_stages:
        engine = engines["alignment"] or _STAGE_DEFAULT_ENGINES["alignment"]
        align_audio = alignment_audio_path or audio_path
        if alignment_audio_path:
            print(f"[PostProcess Pipeline] Using alignment audio: {alignment_audio_path}")
        try:
            result = run_alignment(result, align_audio, engine=engine,
                                   options=alignment_options, language=language,
                                   callback=_stage_cb("alignment"))
        except Exception as e:
            print(f"[PostProcess Pipeline] Alignment failed ({engine}): {e}, continuing")

    if "diarization" in run_stages:
        engine = engines["diarization"] or _STAGE_DEFAULT_ENGINES["diarization"]
        try:
            result = run_diarization(result, audio_path, engine=engine,
                                     options=diarize_options, callback=_stage_cb("diarization"))
        except Exception as e:
            print(f"[PostProcess Pipeline] Diarization failed ({engine}): {e}, continuing")

    if "punctuation" in run_stages:
        engine = engines["punctuation"] or _STAGE_DEFAULT_ENGINES["punctuation"]
        try:
            result = run_punctuation(result, engine=engine,
                                     options=punctuation_options, language=language,
                                     callback=_stage_cb("punctuation"))
        except Exception as e:
            print(f"[PostProcess Pipeline] Punctuation restoration failed ({engine}): {e}, continuing")

    if callback:
        callback(100, "Post-processing complete")
    return result


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
    委托到 run_post_process_pipeline（签名保持向后兼容）。

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
        Alignment engine name (e.g., "whisperx", "qwen3", "funasr").
    diarize_engine : str, optional
        Diarization engine name (e.g., "pyannote", "cam++", "diarize").
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
    # Get language from ASR result if not provided
    if language is None:
        language = asr_result.get("language", "auto")
        print(f"[PostProcess] Using language from ASR result: {language}")

    if callback:
        callback(50, "Applying post-processing...")

    return run_post_process_pipeline(
        asr_result,
        audio_path,
        vad_engine=vad_engine,
        alignment_engine=alignment_engine,
        diarize_engine=diarize_engine,
        vad_options=vad_options,
        alignment_options=alignment_options,
        diarize_options=diarize_options,
        alignment_audio_path=alignment_audio_path,
        language=language,
        callback=callback,
    )

def list_asr_engines() -> list:
    _load_engines()
    return list(_ENGINES.keys())

def list_vad_engines() -> list:
    """List available VAD engines."""
    return ["silero", "fsmn", "webrtc"]

def list_alignment_engines() -> list:
    """List available word-level alignment engines."""
    return ["whisperx", "qwen3", "funasr"]

def list_diarize_engines() -> list:
    """List available speaker diarization engines."""
    return ["pyannote", "cam++"]