"""MOSS-Transcribe-Diarize local ASR engine.

端到端模型 (OpenMOSS-Team/MOSS-Transcribe-Diarize, 0.9B MoE)，单次推理联合完成：
  - 语音识别（支持 50+ 语言）
  - 说话人分离 (speaker diarization)
  - 时间戳对齐（句/段级时间戳）
  - 声音事件感知

模型通过 ModelScope 自动下载到项目固定目录 `_model_cache` 下；
若不存在则首次调用时自动下载。

依赖（需在 venv 中安装）：
  - transformers>=5.6.0
  - torch>=2.8（含 torchaudio）
  - modelscope
  - librosa, soundfile, av, soxr, numba 等
  - 可选 flash-attn（加速）
这些依赖与现有 whisperx/funasr 引擎版本差异较大，请单独确认安装。
"""
import os
import sys
import gc
import json
import time
import threading
from pathlib import Path
from typing import Callable, Optional

from backend.asr.asr_base import ASRBase

# ── 路径与缓存 ───────────────────────────────────────────────────────────
# MOSS 推理代码包位于 backend/asr/MOSS-Transcribe-Diarize，
# 需要把它加入 sys.path 才能 `import moss_transcribe_diarize`。
_MOSS_DIR = Path(__file__).resolve().parent / "MOSS-Transcribe-Diarize"
if str(_MOSS_DIR) not in sys.path:
    sys.path.insert(0, str(_MOSS_DIR))

# 模型固定缓存目录：项目根目录下的 _model_cache
_ROOT = Path(__file__).resolve().parents[2]
_MODEL_CACHE = os.environ.get("MODEL_CACHE_DIR") or str(_ROOT / "_model_cache")

# ModelScope 上的模型仓库 id
MODELSCOPE_MODEL_ID = "openmoss/MOSS-Transcribe-Diarize"
# HuggingFace 上的仓库 id（仅作文档/备用）
HF_MODEL_ID = "OpenMOSS-Team/MOSS-Transcribe-Diarize"

# transformers 补丁目录：用户单独下载的 transformers-5.6.0 及其依赖
_TRANSFORMERS_PATCH_DIR = _ROOT / "venv312" / "packages" / "transformers-560"


def _patch_transformers():
    """让 MOSS 从独立的 transformers-5.6.0 目录加载，避免与全局旧版冲突。

    必须在 import transformers 之前调用。做法：
      1. 把补丁目录本身（父目录）插入 sys.path 最前，使 transformers /
         huggingface_hub 等都能正确定位到补丁内的包（注意：必须加父目录，
         而非把每个子包目录直接加入 sys.path，否则 `import transformers`
         会去找 <补丁>/transformers/transformers/__init__.py 而失败）；
      2. 预导入标准库 dataclasses，避免补丁内 huggingface_hub/dataclasses.py
         的同名子模块抢占标准库导致循环导入；
      3. 把 site-packages 中可用的 regex 预注入 sys.modules，避免补丁目录里
         损坏/不兼容的 regex 扩展覆盖标准可用版本；
      4. 清除进程内已缓存的旧版 transformers / huggingface_hub，强制重新导入。
    """
    patch_dir = str(_TRANSFORMERS_PATCH_DIR)
    if not os.path.isdir(patch_dir):
        print(f"[MOSS] transformers 补丁目录不存在: {patch_dir}，回退使用系统 transformers", flush=True)
        return

    # 1) 补丁目录（父目录）前置
    if patch_dir not in sys.path:
        sys.path.insert(0, patch_dir)

    # 2) 标准库 dataclasses 预导入（关键，避免 huggingface_hub 同名子模块冲突）
    import dataclasses  # noqa: F401

    # 3) 用 site-packages 的 regex 覆盖补丁内可能损坏的 regex
    sp_regex = os.path.join(sys.prefix, "Lib", "site-packages", "regex")
    if os.path.isdir(sp_regex) and os.path.isfile(os.path.join(sp_regex, "__init__.py")):
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "regex", os.path.join(sp_regex, "__init__.py"),
                submodule_search_locations=[sp_regex])
            _mod = _ilu.module_from_spec(_spec)
            sys.modules["regex"] = _mod
            _spec.loader.exec_module(_mod)
            print(f"[MOSS] 使用 site-packages 的 regex: {_mod.__file__}", flush=True)
        except Exception as e:
            print(f"[MOSS] 注入 site-packages regex 失败，将回退使用补丁内 regex: {e}", flush=True)

    # 4) 清除已缓存的旧版 transformers / huggingface_hub，确保从补丁重新导入
    for name in list(sys.modules):
        if (name == "transformers" or name.startswith("transformers.")
                or name == "huggingface_hub" or name.startswith("huggingface_hub.")):
            del sys.modules[name]
    print(f"[MOSS] transformers 已打补丁，加载目录: {patch_dir}", flush=True)


class MossTranscribeDiarizeLocal(ASRBase):
    """MOSS-Transcribe-Diarize 本地推理引擎。

    该模型本身一次性输出带时间戳、说话人标签的转录文本，
    因此 VAD / 对齐 / 说话人识别均视为“内部已执行”，
    避免下游重复运行后处理。本引擎额外为每段合成 word 级时间戳
    （按段首尾时间线性插值），以兼容依赖 words 字段的下游步骤
    （句子切分、翻译、TTS 时间轴）。
    """

    _model_lock = threading.Lock()
    # 进程内缓存：(model, processor, dtype, device, model_path)
    _cached: Optional[tuple] = None

    def __init__(self):
        self.model_id = MODELSCOPE_MODEL_ID
        self._model_cache = _MODEL_CACHE

    # ── 模型下载/解析 ───────────────────────────────────────────────────
    def _resolve_model_path(self) -> Optional[str]:
        """若存在已下载且完整的本地模型，返回其路径；否则返回 None。

        先尝试用 modelscope 的 local_files_only 获取缓存路径
        （不触发下载），再回退到标准目录布局做一次兜底检查。
        仅当目录中确实存在 ``config.json`` 时才认为模型已就绪，
        避免被 modelscope 的 ``.mdl`` 下载标记文件欺骗而误判为已缓存。
        """
        candidates: list[str] = []
        try:
            from modelscope import snapshot_download
            local = snapshot_download(
                self.model_id, cache_dir=self._model_cache, local_files_only=True
            )
            if local and os.path.isdir(local):
                candidates.append(os.path.abspath(local))
        except Exception:
            pass
        # 兜底：标准 modelscope 布局
        candidates.append(
            os.path.abspath(
                os.path.join(self._model_cache, "openmoss", "MOSS-Transcribe-Diarize")
            )
        )

        for path in candidates:
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "config.json")):
                return path
        return None

    def _ensure_model_downloaded(self, callback: Optional[Callable] = None) -> str:
        existing = self._resolve_model_path()
        if existing:
            return existing
        if callback:
            callback(6, f"正在下载 MOSS 模型 {self.model_id} ...")
        print(f"[MOSS] Model not cached, downloading {self.model_id} -> {self._model_cache}", flush=True)
        from modelscope import snapshot_download
        local = snapshot_download(self.model_id, cache_dir=self._model_cache)
        print(f"[MOSS] Downloaded model -> {local}", flush=True)
        return os.path.abspath(local)

    # ── 模型加载 ────────────────────────────────────────────────────────
    def _get_model(self, callback: Optional[Callable] = None):
        if MossTranscribeDiarizeLocal._cached is not None:
            return MossTranscribeDiarizeLocal._cached

        # 关键：在 import transformers / moss 之前打补丁，切换到独立的 transformers-5.6.0
        _patch_transformers()

        from transformers import AutoProcessor
        from moss_transcribe_diarize.attention import load_model_with_attention_fallback
        from moss_transcribe_diarize.inference_utils import dtype_from_name, resolve_device

        model_path = self._ensure_model_downloaded(callback)
        device = resolve_device("auto")
        # 显存充足用 bf16，CPU 回退 fp16；必须转成 torch.dtype，
        # 否则 flash 预检与 autocast 会把字符串当成非法 dtype 而失效
        requested_dtype = dtype_from_name("bf16" if str(device).startswith("cuda") else "fp16")

        if callback:
            callback(12, f"加载 MOSS 模型 (device={device}, dtype={requested_dtype})...")

        model, attention_report = load_model_with_attention_fallback(
            model_path, device=device, dtype=requested_dtype
        )
        # 加载器不会自动把权重搬到目标设备/精度（仅传 dtype 不会移动权重），
        # 必须显式 .to(device)，否则 input_ids 在 cuda、权重在 cpu 会直接报错
        model = model.to(device)
        if next(model.parameters()).dtype != requested_dtype:
            model = model.to(requested_dtype)
        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)

        MossTranscribeDiarizeLocal._cached = (
            model, processor, requested_dtype, device, model_path
        )
        print(f"[MOSS] Model loaded (device={device}, dtype={requested_dtype})", flush=True)
        return MossTranscribeDiarizeLocal._cached

    @staticmethod
    def _release_model():
        MossTranscribeDiarizeLocal._cached = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # ── 提示词构建 ──────────────────────────────────────────────────────
    @staticmethod
    def _build_prompt(hotwords: Optional[str] = None, diarize: bool = True) -> str:
        from moss_transcribe_diarize.inference_utils import DEFAULT_PROMPT

        prompt = DEFAULT_PROMPT
        if hotwords and hotwords.strip():
            prompt = (
                prompt
                + f"\n本次音频涉及的专有名词与热点词汇（请优先正确识别）：{hotwords.strip()}"
            )
        # MOSS 默认提示词已包含说话人分离指令；diarize=False 时不强行关闭，
        # 因为模型始终输出说话人标签，关闭会导致解析异常。
        return prompt

    # ── word 级时间戳合成 ───────────────────────────────────────────────
    @staticmethod
    def _synthesize_words(text: str, start: float, end: float) -> list:
        """MOSS 仅提供段级时间戳，这里按字符/词线性插值合成 word 时间戳，
        以兼容依赖 words 的下游步骤。中文按字切分，其他语言按空白切分。"""

        text = (text or "").strip()
        if not text:
            return []

        tokens: list = []
        buf = ""
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
            elif ch.isspace():
                if buf:
                    tokens.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            tokens.append(buf)
        # 去掉纯空白 token
        tokens = [t for t in tokens if t.strip()]
        if not tokens:
            return []

        dur = max(0.0, float(end) - float(start))
        n = len(tokens)
        words = []
        for i, tok in enumerate(tokens):
            w_start = float(start) + dur * i / n
            w_end = float(start) + dur * (i + 1) / n
            words.append({
                "word": tok,
                "start": round(w_start, 4),
                "end": round(w_end, 4),
            })
        return words

    # ── 主入口 ──────────────────────────────────────────────────────────
    def transcribe(
        self,
        input_path: str,
        output_path: Optional[str],
        callback: Optional[Callable] = None,
        *,
        model=None,
        language: Optional[str] = None,
        hotwords: Optional[str] = None,
        diarize: bool = True,
        num_speakers: Optional[int] = None,
        use_itn: Optional[bool] = None,
        **kwargs,
    ) -> dict:
        if callback:
            callback(3, "准备 MOSS-Transcribe-Diarize 模型...")

        model_tuple = self._get_model(callback)
        model, processor, dtype, device, model_path = model_tuple

        from moss_transcribe_diarize.inference_utils import (
            build_transcription_messages,
            generate_transcription,
        )
        from moss_transcribe_diarize import parse_transcript

        prompt = self._build_prompt(hotwords=hotwords, diarize=diarize)
        messages = build_transcription_messages(input_path, prompt=prompt)

        if callback:
            callback(35, "MOSS 推理中（识别 + 分离 + 对齐）...")

        t0 = time.time()
        with MossTranscribeDiarizeLocal._model_lock:
            result = generate_transcription(
                model,
                processor,
                messages,
                max_new_tokens=2048,
                do_sample=False,
                device=device,
                dtype=dtype,
            )
        raw_text = result.get("text", "")
        print(f"[MOSS] Inference done in {time.time() - t0:.1f}s", flush=True)

        if callback:
            callback(85, "解析转录结果...")

        parsed = parse_transcript(raw_text)

        segments: list = []
        speakers: set = set()
        for i, seg in enumerate(parsed):
            start = float(getattr(seg, "start", 0) or 0)
            end = float(getattr(seg, "end", 0) or 0)
            text = (getattr(seg, "text", "") or "").strip()
            speaker = getattr(seg, "speaker", None) or ""
            if speaker:
                speakers.add(speaker)
            words = self._synthesize_words(text, start, end)
            segments.append({
                "id": i + 1,
                "start": round(start, 4),
                "end": round(end, 4),
                "text": text,
                "speaker_id": speaker,
                "words": words,
            })

        full_text = " ".join(s["text"] for s in segments if s["text"]).strip()

        output: dict = {
            "text": full_text,
            "segments": segments,
            "language": language or "auto",
            "model": f"MOSS-Transcribe-Diarize ({model_path})",
            "speakers": sorted(speakers),
            # 模型已内部完成 VAD / 对齐 / 说话人识别，标记跳过下游冗余后处理
            "_vad_internally_executed": True,
            "_alignment_internally_executed": True,
            "_diarization_internally_executed": True,
        }

        # 写入 output_path（遵循 asr_base 契约）
        if output_path:
            try:
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[MOSS] Warning: failed to write output_path: {e}", flush=True)

        if callback:
            callback(100, "MOSS 转录完成")
        return output

    # 生命周期：空闲卸载由 asr_factory 统一处理；此处提供显式释放接口
    def unload(self):
        MossTranscribeDiarizeLocal._release_model()


# ── 模块级入口（供 SDK 测试接口 _run_asr_sdk 通过 sdk_module/sdk_function 调用）──
def transcribe(
    input_path: str,
    output_path: Optional[str] = None,
    callback: Optional[Callable] = None,
    **kwargs,
) -> dict:
    """模块级 transcribe 包装，实例化引擎并转发调用。

    测试接口 (/api/asr-interfaces/{id}/test) 通过 sdk_module 导入本模块、
    并查找名为 `transcribe` 的模块级函数；因此这里提供一层薄包装。
    """
    engine = MossTranscribeDiarizeLocal()
    return engine.transcribe(input_path, output_path, callback, **kwargs)
