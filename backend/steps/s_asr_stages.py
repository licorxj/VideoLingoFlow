"""ASR 分阶段节点：ASR识别（仅转录）与 ASR后处理（VAD断句/时间戳对齐/说话人识别/标点恢复）。

配合 asr_factory 的分阶段 API，支持把工作流拆成：
  ASR识别节点 ──(subtitle JSON)──> ASR后处理节点
全流程 "asr" 节点仍然一次性执行（见 s02_asr.S02ASR）。

ASR后处理节点配置（节点级 > 全局设置 > 内置默认）：
  - run_vad / run_alignment / run_diarization / run_punctuation：阶段执行勾选
  - vad_engine / alignment_engine / diarize_engine / punc_engine：各阶段模型（留空跟随全局设置）
  - vad_onset / vad_offset、alignment_model、dtype、
    num_speakers / min_speakers / max_speakers：模型可选设置
  - force_rerun：强制重新执行（默认关闭：上游结果已有有效后处理产物时跳过对应阶段）
"""
import os
import json
from typing import Callable, Optional, Dict, Any

from backend.steps.base_step import BaseStep, find_artifact
from backend.steps.s02_asr import (
    S02ASR,
    resolve_asr_audio_inputs,
    _get_audio_duration,
    _normalize_asr_result,
    _clamp_result_to_duration,
    _resolve_input_language,
)

# 各阶段引擎留空时的内置默认（与全局设置默认值一致）
_STAGE_DEFAULT_ENGINES = {"vad": "fsmn", "alignment": "whisperx", "diarization": "diarize", "punctuation": "ct_punc"}


class S_ASRRecognize(S02ASR):
    """ASR识别节点：只做语音识别（含长音频分段转录），不执行任何后处理。

    输出为规范化后的原始识别结果，供下游 ASR后处理 节点继续处理。
    """

    _node_type = "asr_recognize"

    def _apply_post_processing(self, result: dict, audio_path: str, engine_id: str,
                              callback=None, cancel_callback=None) -> dict:
        # 识别节点跳过全部后处理（VAD/对齐/说话人由下游后处理节点按需执行）
        print("[ASR Recognize] Post-processing skipped (recognition-only node)")
        return result


class S_ASRPostProcess(BaseStep):
    """ASR后处理节点：对上游 ASR 结果 JSON 按勾选执行 VAD断句/时间戳对齐/说话人识别。"""

    step_id = "asr_postprocess"
    step_name = "ASR后处理"
    dependencies = []
    artifacts = []

    _node_type = "asr_postprocess"

    def __init__(self):
        pass

    def check_artifact(self, task_dir: str) -> bool:
        return find_artifact(os.path.join(task_dir, "cache"), "asr_postprocessed.json") is not None

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        subtitle = step_inputs.get("subtitle", "")
        if not subtitle:
            return False
        p = subtitle if os.path.isabs(subtitle) else os.path.join(task_dir, subtitle)
        return os.path.exists(p)

    # ── config helpers ────────────────────────────────────────────────

    def _load_node_config(self, task_dir: str) -> Dict[str, Any]:
        """节点配置：优先运行时注入的 _node_config，回退扫描 workflow.json。"""
        injected = getattr(self, "_node_config", None)
        if injected:
            return dict(injected)
        try:
            from backend.steps.s02_asr import _load_task_node_config
            return _load_task_node_config(task_dir, self._node_type)
        except Exception:
            return {}

    @staticmethod
    def _flag(cfg: Dict[str, Any], key: str, default: bool) -> bool:
        v = cfg.get(key)
        if v is None:
            return default
        return v is True or str(v).lower() == "true"

    @staticmethod
    def _resolve_engine(cfg: Dict[str, Any], cfg_key: str,
                        global_key: str, default: str) -> str:
        """阶段引擎解析：节点配置 > 全局设置 > 内置默认。"""
        val = cfg.get(cfg_key)
        if val:
            return str(val)
        try:
            from backend.config.config_manager import config
            g = config.get(global_key)
            if g:
                return str(g)
        except Exception:
            pass
        return default

    @staticmethod
    def _num(cfg: Dict[str, Any], key: str) -> Optional[int]:
        v = cfg.get(key)
        if v in (None, ""):
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _float(cfg: Dict[str, Any], key: str) -> Optional[float]:
        v = cfg.get(key)
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    # ── 防重复执行判定（内部标志 + 数据启发式） ──────────────────────

    @staticmethod
    def _already_vad_done(result: Dict[str, Any]) -> bool:
        """上游引擎已内置 VAD，或 segments 已普遍带有有效时间段（无需再断句）。"""
        if result.get("_vad_internally_executed"):
            return True
        segs = result.get("segments", []) or []
        if not segs:
            return False
        valid = 0
        for s in segs:
            try:
                if float(s.get("end") or 0) > float(s.get("start") or 0):
                    valid += 1
            except (TypeError, ValueError):
                pass
        return valid >= max(1, int(len(segs) * 0.8))

    @staticmethod
    def _already_aligned(result: Dict[str, Any]) -> bool:
        """上游引擎已内置对齐，或过半 segments 已带有效词级时间戳。"""
        if result.get("_alignment_internally_executed"):
            return True
        segs = result.get("segments", []) or []
        if not segs:
            return False

        def _words_valid(seg) -> bool:
            for w in (seg.get("words") or []):
                try:
                    if float(w.get("end") or 0) > float(w.get("start") or 0):
                        return True
                except (TypeError, ValueError):
                    continue
            return False

        ok = sum(1 for s in segs if s.get("words") and _words_valid(s))
        return ok >= max(1, int(len(segs) * 0.5))

    @staticmethod
    def _already_diarized(result: Dict[str, Any]) -> bool:
        """上游引擎已内置说话人识别，或结果中已含说话人标注。"""
        if result.get("_diarization_internally_executed"):
            return True
        if result.get("speakers"):
            return True
        return any(
            s.get("speaker_id") or s.get("speaker")
            for s in (result.get("segments", []) or [])
        )

    def _build_stage_options(self, cfg: Dict[str, Any], engines: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
        """从节点配置构建各阶段模型可选设置。"""
        vad_options: Dict[str, Any] = {}
        onset = self._float(cfg, "vad_onset")
        offset = self._float(cfg, "vad_offset")
        if onset is not None:
            vad_options["vad_onset"] = onset
        if offset is not None:
            vad_options["vad_offset"] = offset

        alignment_options: Dict[str, Any] = {}
        align_model = cfg.get("alignment_model") or ""
        if align_model:
            # whisperx/funasr 对齐器用 model_name，qwen3 对齐器用 aligner_model
            if engines["alignment"] == "qwen3":
                alignment_options["aligner_model"] = str(align_model)
            else:
                alignment_options["model_name"] = str(align_model)
        dtype = cfg.get("dtype") or ""
        if dtype:
            alignment_options["dtype"] = str(dtype)

        diarize_options: Dict[str, Any] = {}
        for key in ("num_speakers", "min_speakers", "max_speakers"):
            val = self._num(cfg, key)
            if val is not None:
                diarize_options[key] = val
        diarize_model = cfg.get("diarize_model") or ""
        if diarize_model:
            diarize_options["model_name"] = str(diarize_model)

        return {
            "vad": vad_options,
            "alignment": alignment_options,
            "diarization": diarize_options,
            "punctuation": {},
        }

    # ── main entry ────────────────────────────────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(2, "Initializing ASR post-processing...")

        self._task_dir = task_dir
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # 1) 读取上游 ASR 结果 JSON
        subtitle = step_inputs.get("subtitle", "")
        subtitle_path = subtitle if os.path.isabs(subtitle) else os.path.join(task_dir, subtitle)
        if not os.path.exists(subtitle_path):
            raise FileNotFoundError(f"ASR后处理输入缺失：找不到 ASR 结果 JSON '{subtitle}'")
        with open(subtitle_path, "r", encoding="utf-8") as f:
            asr_result = json.load(f)

        # 2) 解析音频输入（VAD/说话人需要音源；优先人声，其次 ASR 音源/缓存回退）
        audio_io = resolve_asr_audio_inputs(task_dir, step_inputs)
        post_process_audio = audio_io["post_process_audio"]
        alignment_audio = audio_io["alignment_audio"]

        # 3) 节点配置与阶段决策
        cfg = self._load_node_config(task_dir)
        run_vad = self._flag(cfg, "run_vad", True)
        run_alignment = self._flag(cfg, "run_alignment", True)
        run_diarization = self._flag(cfg, "run_diarization", False)
        # 标点恢复默认开启：阶段内部有语言门控+标点密度检测，已有标点时零开销跳过
        run_punctuation = self._flag(cfg, "run_punctuation", True)

        # 3.5) 防重复执行：上游 ASR 接口可能已一次性执行了识别+后处理，
        # 结果中已有有效后处理产物时默认跳过对应阶段，避免浪费与错误叠加；
        # 勾选 force_rerun 时强制重新执行全部勾选阶段。
        if not self._flag(cfg, "force_rerun", False):
            if run_vad and self._already_vad_done(asr_result):
                run_vad = False
                print("[ASR PostProcess Node] VAD skipped: input already has valid VAD segmentation")
            if run_alignment and self._already_aligned(asr_result):
                run_alignment = False
                print("[ASR PostProcess Node] Alignment skipped: input already has word-level timestamps")
            if run_diarization and self._already_diarized(asr_result):
                run_diarization = False
                print("[ASR PostProcess Node] Diarization skipped: input already has speaker labels")

        engines = {
            "vad": self._resolve_engine(cfg, "vad_engine", "asr.post_process.vad.engine", _STAGE_DEFAULT_ENGINES["vad"]),
            "alignment": self._resolve_engine(cfg, "alignment_engine", "asr.post_process.alignment.engine", _STAGE_DEFAULT_ENGINES["alignment"]),
            "diarization": self._resolve_engine(cfg, "diarize_engine", "asr.post_process.diarization.engine", _STAGE_DEFAULT_ENGINES["diarization"]),
            "punctuation": self._resolve_engine(cfg, "punc_engine", "asr.post_process.punctuation.engine", _STAGE_DEFAULT_ENGINES["punctuation"]),
        }
        stages = []
        if run_vad:
            stages.append("vad")
        if run_alignment:
            stages.append("alignment")
        if run_diarization:
            stages.append("diarization")
        if run_punctuation:
            stages.append("punctuation")

        print(f"[ASR PostProcess Node] stages={stages}, engines={engines}")

        # 4) 语言：ASR结果 > 节点配置 > input 节点 > auto
        language = asr_result.get("language", "")
        if not language or language == "auto":
            language = cfg.get("language", "")
        if not language or language == "auto" or language == "from_input":
            language = _resolve_input_language(task_dir)

        # 5) 执行后处理流水线（各阶段独立容错）
        result = asr_result
        if stages:
            if cancel_callback and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError
                raise TaskCancelledError("Cancelled by user")

            from backend.asr.asr_factory import run_post_process_pipeline

            options = self._build_stage_options(cfg, engines)
            try:
                result = run_post_process_pipeline(
                    asr_result,
                    post_process_audio,
                    stages=stages,
                    vad_engine=engines["vad"],
                    alignment_engine=engines["alignment"],
                    diarize_engine=engines["diarization"],
                    punctuation_engine=engines["punctuation"],
                    vad_options=options["vad"],
                    alignment_options=options["alignment"],
                    diarize_options=options["diarization"],
                    punctuation_options=options["punctuation"],
                    alignment_audio_path=alignment_audio,
                    language=language,
                    callback=lambda pct, msg: callback(5 + int(pct * 0.85), msg) if callback else None,
                )
            except Exception as e:
                print(f"[ASR PostProcess Node] Pipeline error: {e}, returning input result")

        # 6) 收尾：规范化并钳制到音源时长（与全流程节点一致）
        result = _normalize_asr_result(result)
        audio_duration = _get_audio_duration(post_process_audio)
        if audio_duration > 0:
            result = _clamp_result_to_duration(result, audio_duration)

        node_suffix = f"_{self._node_id}" if getattr(self, "_node_id", "") else ""
        output_path = os.path.join(task_dir, "cache", f"asr_postprocessed{node_suffix}.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        seg_count = len(result.get("segments", []))
        if callback:
            callback(100, f"ASR post-processing completed: {seg_count} segments")
        return {
            "artifacts": [f"cache/asr_postprocessed{node_suffix}.json"],
            "outputs": {
                "subtitle": f"cache/asr_postprocessed{node_suffix}.json",
            },
        }
