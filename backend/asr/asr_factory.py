"""ASR factory: creates ASR engine instances by name.

引擎生命周期：空闲超过 5 秒无任务调用时自动卸载（模型多在 transcribe 内以局部
变量使用、调用结束已释放，此处主要归还 torch 显存缓存），下次调用按需重建。
"""
import os
import json
import tempfile
import shutil
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
    try:
        from backend.asr.asr_moss import MossTranscribeDiarizeLocal
        _ENGINES["moss"] = MossTranscribeDiarizeLocal()
    except ImportError as e:
        # 依赖缺失（transformers>=5.6 / torch>=2.8 等）时静默跳过，避免影响其他引擎
        print(f"[ASR Factory] moss engine unavailable: {e}")

def get_asr_engine(name: str) -> ASRBase:
    _load_engines()
    engine = _ENGINES.get(name)
    if engine is None:
        print(f"Unknown ASR engine: {name}, falling back to whisperx_local")
        engine = _ENGINES["whisperx_local"]
    return _REGISTRY.acquire(
        name, lambda: engine, unloader=_asr_unloader,
        busy_check=lambda: bool(getattr(engine, "_busy", False)),
    )

def _resolve_max_duration(engine_name, interface_id, explicit, extra_kwargs):
    """解析切分阈值（秒）：显式参数 > extra_kwargs.max_duration > 接口配置。"""
    def _to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    md = _to_float(explicit)
    if md > 0:
        return md
    md = _to_float(extra_kwargs.get("max_duration"))
    if md > 0:
        return md
    try:
        from backend.asr.asr_interface_manager import get_asr_interface_manager
        cfg = get_asr_interface_manager().get(interface_id or engine_name)
        if cfg:
            md = _to_float(cfg.get("config", {}).get("max_duration"))
            if md > 0:
                return md
    except Exception:
        pass
    return 0.0


def _run_asr_single(engine_name, input_path, output_path, callback,
                    model, language, extra_kwargs):
    """单文件转录（GPU 服务或进程内），不做切分。"""
    # 云端 ASR 引擎（MiMo / ElevenLabs 等，CLOUD=True）不占本地 GPU，跳过 GPU 服务
    # lane 队列，避免与本地模型争用 lane、在显存不足时无 lane 可派发而长时间排队。
    try:
        engine = get_asr_engine(engine_name)
        if not getattr(engine, "CLOUD", False):
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
    engine._busy = True
    try:
        return engine.transcribe(
            input_path, output_path,
            callback=callback, model=model, language=language,
            **extra_kwargs,
        )
    finally:
        engine._busy = False


def _run_asr_chunked(engine_name, input_path, output_path, callback,
                     model, language, extra_kwargs, interface_id,
                     max_duration, duration):
    """按时长安全切分音频，逐段推理后重新组装时间戳（集中处理）。

    切分策略与安全下刀方法参考 audio_split.split_audio_at_silence（静音边界），
    时间戳偏移/重组装参考 audio_split.adjust_timestamps / merge_results。
    """
    from backend.asr import audio_split as sp
    segments = sp.split_audio_at_silence(input_path, max_duration)
    print(f"[ASR] Audio split into {len(segments)} segments: {segments}")
    if callback:
        callback(5, f"Splitting audio ({duration:.0f}s) into {len(segments)} segments")

    n = len(segments)
    tmp_dir = tempfile.mkdtemp(prefix="asr_split_")
    all_results = []
    try:
        for i, (start, end) in enumerate(segments):
            if callback:
                callback(10 + int(80 * i / n),
                         f"Transcribing segment {i + 1}/{n} ({start:.1f}s-{end:.1f}s)")
            seg_path = os.path.join(tmp_dir, f"seg_{i:04d}.wav")
            sp.cut_audio_segment(input_path, start, end, seg_path)
            seg_out = os.path.join(tmp_dir, f"result_{i:04d}.json")

            def _cb(pct, msg, _i=i, _n=n):
                if callback:
                    callback(10 + int(80 * (_i + pct / 100.0) / _n), msg)

            res = _run_asr_single(engine_name, seg_path, seg_out, _cb,
                                  model, language, extra_kwargs)
            sp.adjust_timestamps(res, start)
            all_results.append(res)

            # 释放段间显存碎片，防止长音频 OOM
            try:
                import gc as _gc
                _gc.collect()
                import torch as _torch
                if _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
            except Exception:
                pass

        merged = sp.merge_results(all_results)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        return merged
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_asr(
    input_path: str, output_path: str, callback=None,
    *, engine_name=None, interface_id=None,
    model=None, language=None, max_duration=None, **extra_kwargs,
) -> dict:
    """执行 ASR 转录；当音频时长超过接口配置的 max_duration 时，自动按静音边界
    安全切分、逐段推理、再重组装时间戳（集中处理）。"""
    engine_name = engine_name or "whisperx_local"
    md = _resolve_max_duration(engine_name, interface_id, max_duration, extra_kwargs)
    extra_kwargs.pop("max_duration", None)
    duration = 0.0
    try:
        from backend.asr.audio_split import get_audio_duration
        duration = get_audio_duration(input_path)
    except Exception:
        pass
    if md and duration and duration > md:
        result = _run_asr_chunked(
            engine_name, input_path, output_path, callback,
            model, language, extra_kwargs, interface_id, md, duration,
        )
    else:
        result = _run_asr_single(
            engine_name, input_path, output_path, callback,
            model, language, extra_kwargs,
        )
    # 统一说话人字段格式（speaker_id -> speaker，并下放到词级）
    from backend.asr.asr_base import normalize_speaker_format
    return normalize_speaker_format(result)


def run_asr_with_post_processing(
    input_path: str,
    output_path: str,
    callback=None,
    *,
    engine_name: str = "whisperx_local",
    interface_id: Optional[str] = None,
    model: str = None,
    language: str = None,
    max_duration: Optional[float] = None,
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
    # Step 1: Run ASR（集中处理：超过 max_duration 时自动切分并重组装时间戳）
    if callback:
        callback(10, f"Running ASR with {engine_name}...")

    engine_name = engine_name or "whisperx_local"
    md = _resolve_max_duration(engine_name, interface_id, max_duration, extra_kwargs)
    extra_kwargs.pop("max_duration", None)
    duration = 0.0
    try:
        from backend.asr.audio_split import get_audio_duration
        duration = get_audio_duration(input_path)
    except Exception:
        pass

    if md and duration and duration > md:
        asr_result = _run_asr_chunked(
            engine_name, input_path, output_path, callback,
            model, language, extra_kwargs, interface_id, md, duration,
        )
    else:
        asr_result = _run_asr_single(
            engine_name, input_path, output_path, callback,
            model, language, extra_kwargs,
        )

    # Step 2: Apply post-processing if requested
    if vad_engine or alignment_engine or diarize_engine:
        if callback:
            callback(40, "Starting post-processing...")

        # Use the engine's post_process method
        engine = get_asr_engine(engine_name)
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

    # 统一说话人字段格式（speaker_id -> speaker，并下放到词级）
    from backend.asr.asr_base import normalize_speaker_format
    return normalize_speaker_format(asr_result)

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
    print(f"[Pipeline.VAD] >>> START engine={engine} audio={audio_path} options={options or {}}", flush=True)
    if callback:
        callback(0, f"Running VAD with {engine}...")
    print(f"[Pipeline.VAD] calling _apply_vad...", flush=True)
    result = _make_temp_engine()._apply_vad(
        asr_result.copy(), audio_path, engine, options or {}
    )
    seg_count = len(result.get("segments", []) or [])
    print(f"[Pipeline.VAD] <<< END segments={seg_count}", flush=True)
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
    print(f"[Pipeline.ALIGN] >>> START engine={engine} audio={audio_path} language={language} options={options or {}}", flush=True)
    if callback:
        callback(0, f"Applying word alignment with {engine}...")
    print(f"[Pipeline.ALIGN] calling _apply_alignment...", flush=True)
    result = _make_temp_engine()._apply_alignment(
        asr_result.copy(), audio_path, engine, options or {}, language
    )
    seg_count = len(result.get("segments", []) or [])
    print(f"[Pipeline.ALIGN] <<< END segments={seg_count}", flush=True)
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
    print(f"[Pipeline.DIAR] >>> START engine={engine} audio={audio_path}", flush=True)
    if callback:
        callback(0, f"Applying speaker diarization with {engine}...")
    result = _make_temp_engine()._apply_diarization(
        asr_result.copy(), audio_path, engine, options or {}
    )
    print(f"[Pipeline.DIAR] <<< END", flush=True)
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
    print(f"[Pipeline.PUNC] >>> START engine={engine} language={language}", flush=True)
    if callback:
        callback(0, f"Restoring punctuation with {engine}...")
    result = _make_temp_engine()._apply_punctuation(
        asr_result.copy(), engine, options or {}, language
    )
    print(f"[Pipeline.PUNC] <<< END", flush=True)
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
    # 规范化为 ISO 码：上游 ASR 引擎可能返回 "English"/"Chinese" 全称，
    # 而 WhisperX/FunASR 等下游引擎只认识 "en"/"zh" 两字母码
    from backend.asr.punctuation_processor import normalize_lang_code
    _norm_lang = normalize_lang_code(language)
    if _norm_lang:
        language = _norm_lang

    result = asr_result.copy()
    # 各阶段进度窗口：vad [0,35) / alignment [35,65) / diarization [65,90) / punctuation [90,100]
    windows = {"vad": (0, 35), "alignment": (35, 65), "diarization": (65, 90), "punctuation": (90, 100)}
    print(f"[Pipeline] run_stages={run_stages} language={language}", flush=True)

    def _stage_cb(stage):
        if not callback:
            return None
        lo, hi = windows[stage]
        return lambda pct, msg: callback(lo + int(pct * (hi - lo) / 100), msg)

    if "vad" in run_stages:
        engine = engines["vad"] or _STAGE_DEFAULT_ENGINES["vad"]
        print(f"[Pipeline] --- stage VAD (engine={engine}) ---", flush=True)
        try:
            result = run_vad(result, audio_path, engine=engine,
                             options=vad_options, callback=_stage_cb("vad"))
        except Exception as e:
            import traceback as _tb
            print(f"[Pipeline] VAD failed ({engine}): {e}\n{_tb.format_exc()}", flush=True)

    if "alignment" in run_stages:
        engine = engines["alignment"] or _STAGE_DEFAULT_ENGINES["alignment"]
        align_audio = alignment_audio_path or audio_path
        if alignment_audio_path:
            print(f"[Pipeline] Using alignment audio: {alignment_audio_path}", flush=True)
        print(f"[Pipeline] --- stage ALIGNMENT (engine={engine} audio={align_audio}) ---", flush=True)
        try:
            result = run_alignment(result, align_audio, engine=engine,
                                   options=alignment_options, language=language,
                                   callback=_stage_cb("alignment"))
        except Exception as e:
            import traceback as _tb
            print(f"[Pipeline] Alignment failed ({engine}): {e}\n{_tb.format_exc()}", flush=True)

    if "diarization" in run_stages:
        engine = engines["diarization"] or _STAGE_DEFAULT_ENGINES["diarization"]
        print(f"[Pipeline] --- stage DIARIZATION (engine={engine}) ---", flush=True)
        try:
            result = run_diarization(result, audio_path, engine=engine,
                                     options=diarize_options, callback=_stage_cb("diarization"))
        except Exception as e:
            import traceback as _tb
            print(f"[Pipeline] Diarization failed ({engine}): {e}\n{_tb.format_exc()}", flush=True)

    if "punctuation" in run_stages:
        engine = engines["punctuation"] or _STAGE_DEFAULT_ENGINES["punctuation"]
        print(f"[Pipeline] --- stage PUNCTUATION (engine={engine}) ---", flush=True)
        try:
            result = run_punctuation(result, engine=engine,
                                     options=punctuation_options, language=language,
                                     callback=_stage_cb("punctuation"))
        except Exception as e:
            import traceback as _tb
            print(f"[Pipeline] Punctuation restoration failed ({engine}): {e}\n{_tb.format_exc()}", flush=True)

    print(f"[Pipeline] all stages done", flush=True)
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