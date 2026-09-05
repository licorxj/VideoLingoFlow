"""s06_subtitle_gen: Generate SRT subtitle files from upstream JSON.

兼容上游三种节点输出：
  - s03_sentence_split → sentences.json
  - s05_translate → translation_direct.json / translation_reflect.json
  - s07_subtitle_align → subtitle_aligned.json

输出规则：
  - 只有原文 → 只生成原文字幕
  - 有译文 → 生成译文 / 原文 / 双语三种字幕
"""
import os
import json
import re
from statistics import median
from typing import Callable, Optional, List, Dict, Tuple, Any

from backend.steps.base_step import BaseStep, find_artifact


class S06SubtitleGen(BaseStep):
    step_id = "s06_subtitle_gen"
    step_name = "字幕生成"
    dependencies = []  # 可接多种上游节点，不限定依赖
    artifacts = ["output/subtitles.srt"]
    _PUNCTS_CACHE: Dict[str, Dict[str, set]] = {}

    # ── 输入解析 ────────────────────────────────────────────────────

    @staticmethod
    def _pick_original_text(item: Dict[str, Any]) -> str:
        return (
            item.get("src")
            or item.get("source")
            or item.get("origin")
            or item.get("original")
            or item.get("text")
            or ""
        )

    @staticmethod
    def _pick_translated_text(item: Dict[str, Any]) -> str:
        return (
            item.get("reflect")
            or item.get("free")
            or item.get("tr")
            or item.get("translated")
            or item.get("translation")
            or item.get("direct")
            or ""
        )

    @classmethod
    def _normalize_entries(cls, data: Any) -> List[Dict]:
        """Normalize multiple upstream JSON shapes into subtitle entries.

        支持：
        - list：[{start, end, text, translated?}, ...]（sentences / translation / aligned 产物）
        - dict：ASR 结果格式 {"segments": [{id, start, end, text}], ...}（如 OCR字幕识别输出）
        """
        if isinstance(data, dict):
            data = data.get("segments") or []
        if not isinstance(data, list):
            return []

        entries: List[Dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            text = cls._pick_original_text(item).strip()
            translated = cls._pick_translated_text(item).strip()
            entry = {
                "start": item.get("start", 0),
                "end": item.get("end", item.get("start", 0) + 5),
                "text": text,
            }
            if translated:
                entry["translated"] = translated
            entries.append(entry)
        return entries

    @staticmethod
    def _prefer_reflect_path(path: str) -> str:
        """Prefer reflective translation output when direct translation is provided."""
        basename = os.path.basename(path)
        if basename != "translation_direct.json" and not basename.startswith("translation_direct_"):
            return path
        reflect_path = find_artifact(os.path.dirname(path), "translation_reflect.json")
        return reflect_path if reflect_path else path

    @classmethod
    def _load_json_entries(cls, json_path: str) -> Tuple[List[Dict], bool]:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = cls._normalize_entries(data)
        return entries, any(e.get("translated") for e in entries)

    def _resolve_languages_from_input(self, task_dir: str) -> Tuple[str, str]:
        """Read source_language and target_language from input node in workflow.json."""
        src_lang = "auto"
        tgt_lang = "zh"
        wf_path = os.path.join(task_dir, "workflow.json")
        if os.path.exists(wf_path):
            try:
                with open(wf_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                for node in wf.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        cfg = node.get("data", {}).get("config", {})
                        src = cfg.get("source_language", "")
                        tgt = cfg.get("target_language", "")
                        if src:
                            src_lang = src
                        if tgt:
                            tgt_lang = tgt
                        break
            except Exception:
                pass
        return src_lang, tgt_lang

    @classmethod
    def _load_language_puncts(cls, lang: str = "auto") -> Dict[str, set]:
        """Load punctuation config for a language, merging with _common."""
        cache_key = str(lang or "auto")
        if cache_key in cls._PUNCTS_CACHE:
            return cls._PUNCTS_CACHE[cache_key]

        puncts_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
            "language_puncts.json",
        )
        try:
            with open(puncts_path, "r", encoding="utf-8") as f:
                all_puncts = json.load(f)
        except Exception:
            all_puncts = {}

        lang_value = str(lang or "auto")
        lang_base = lang_value.split("-")[0] if "-" in lang_value else lang_value
        entry = (
            all_puncts.get(lang_value)
            or all_puncts.get(lang_base)
            or all_puncts.get("_default", {})
        )
        # 合并 _common 部分的标点（全角+半角）
        common = all_puncts.get("_common", {})
        sentence_ends = set(entry.get("sentence_ends", [".", "!", "?"])) | set(common.get("sentence_ends", []))
        clause_breaks = set(entry.get("clause_breaks", [","])) | set(common.get("clause_breaks", []))
        result = {
            "sentence_ends": sentence_ends,
            "clause_breaks": clause_breaks,
        }
        cls._PUNCTS_CACHE[cache_key] = result
        return result

    @classmethod
    def _replace_language_punctuation(
        cls,
        text: str,
        lang: str,
        replace_mode: str,
    ) -> str:
        value = str(text or "")
        puncts = cls._load_language_puncts(lang)
        punct_chars = puncts.get("sentence_ends", set()) | puncts.get("clause_breaks", set())
        if not punct_chars:
            return value.rstrip()

        replacement = " " if replace_mode == "space" else ""
        translated = "".join(replacement if char in punct_chars else char for char in value)
        if replace_mode == "space":
            translated = re.sub(r"[ ]{2,}", " ", translated)
        return translated.rstrip()

    @classmethod
    def _apply_punctuation_filter(
        cls,
        entries: List[Dict],
        source_lang: str,
        target_lang: str,
        replace_mode: str,
    ) -> List[Dict]:
        filtered: List[Dict] = []
        for entry in entries:
            item = dict(entry)
            item["text"] = cls._replace_language_punctuation(
                item.get("text", ""),
                source_lang,
                replace_mode,
            )
            if "translated" in item:
                item["translated"] = cls._replace_language_punctuation(
                    item.get("translated", ""),
                    target_lang,
                    replace_mode,
                )
            filtered.append(item)
        return filtered

    @classmethod
    def _resolve_input(cls, task_dir: str, step_inputs: Optional[Dict] = None) -> Tuple[List[Dict], bool]:
        """解析上游 JSON，返回 (entries, is_bilingual)。

        entries 统一格式: [{start, end, text, translated?}, ...]
        is_bilingual=True 时 translated 字段非空。
        """
        step_inputs = step_inputs or {}
        cache_dir = os.path.join(task_dir, "cache")

        subtitle_input = step_inputs.get("subtitle")
        if subtitle_input:
            # 连线注入的路径可能是相对路径（相对 task_dir），需拼接到任务目录再判断
            if not os.path.isabs(subtitle_input):
                subtitle_input = os.path.join(task_dir, subtitle_input)
        if subtitle_input and os.path.exists(subtitle_input):
            if subtitle_input.lower().endswith(".json"):
                subtitle_input = cls._prefer_reflect_path(subtitle_input)
                return cls._load_json_entries(subtitle_input)
            elif subtitle_input.lower().endswith(".srt"):
                entries = []
                blocks = open(subtitle_input, "r", encoding="utf-8").read().strip().split("\n\n")
                for block in blocks:
                    lines = [line for line in block.splitlines() if line.strip()]
                    if len(lines) < 3:
                        continue
                    ts = lines[1]
                    start_s, end_s = ts.split(" --> ")
                    def _parse_ts(value):
                        value = value.replace(",", ".")
                        hh, mm, ss = value.split(":")
                        return int(hh) * 3600 + int(mm) * 60 + float(ss)
                    entries.append({
                        "start": _parse_ts(start_s),
                        "end": _parse_ts(end_s),
                        "text": "\n".join(lines[2:]).strip(),
                    })
                return entries, False

        # 优先级 1: s07_subtitle_align 输出（双语，已对齐）
        aligned_path = find_artifact(cache_dir, "subtitle_aligned.json")
        if aligned_path:
            return cls._load_json_entries(aligned_path)

        # 优先级 2: s05_translate 输出（反思优先，直译兜底）
        reflect_path = find_artifact(cache_dir, "translation_reflect.json")
        direct_path = find_artifact(cache_dir, "translation_direct.json")
        if reflect_path:
            return cls._load_json_entries(reflect_path)
        if direct_path:
            return cls._load_json_entries(direct_path)

        # 兼容旧版 translation.json
        sentences_path = find_artifact(cache_dir, "sentences.json")
        translation_path = os.path.join(cache_dir, "translation.json")
        if sentences_path and os.path.exists(translation_path):
            with open(sentences_path, "r", encoding="utf-8") as f:
                sentences = json.load(f)
            with open(translation_path, "r", encoding="utf-8") as f:
                translations = json.load(f)
            legacy_entries = []
            for i, sent in enumerate(sentences):
                entry = {
                    "start": sent.get("start", 0),
                    "end": sent.get("end", sent.get("start", 0) + 5),
                    "text": sent.get("text", ""),
                }
                if i < len(translations) and translations[i]:
                    entry["translated"] = translations[i]
                legacy_entries.append(entry)
            return legacy_entries, any(e.get("translated") for e in legacy_entries)

        # 优先级 3: s03_sentence_split 输出（单语）
        if sentences_path:
            return cls._load_json_entries(sentences_path)

        return [], False

    # ── SRT 格式化 ──────────────────────────────────────────────────

    @staticmethod
    def _format_ts(seconds: float) -> str:
        """秒数 → SRT 时间戳 HH:MM:SS,mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @classmethod
    def _entries_to_srt(cls, entries: List[Dict], key: str = "text") -> str:
        """将 entries 转为 SRT 字符串，key 指定取哪个字段作为字幕文本。"""
        lines = []
        idx = 0
        for e in entries:
            txt = e.get(key, "").strip()
            if not txt:
                continue
            idx += 1
            lines.append(str(idx))
            lines.append(f"{cls._format_ts(e['start'])} --> {cls._format_ts(e['end'])}")
            lines.append(txt)
            lines.append("")
        return "\n".join(lines)

    @classmethod
    def _entries_to_bilingual_srt(cls, entries: List[Dict]) -> str:
        """将双语 entries 转为合并 SRT（每条字幕两行：原文 + 译文）。

        行序约定：
          - 第 1 行 = primary = 原文字幕
          - 第 2 行 = secondary = 译文字幕
        下游 split_bilingual_srt 会按此顺序拆出 primary/secondary，
        渲染时原文（primary）固定显示在屏幕上方，译文（secondary）固定显示在屏幕下方。
        """
        lines = []
        idx = 0
        for e in entries:
            tr = e.get("translated", "").strip()
            orig = e.get("text", "").strip()
            if not tr and not orig:
                continue
            idx += 1
            lines.append(str(idx))
            lines.append(f"{cls._format_ts(e['start'])} --> {cls._format_ts(e['end'])}")
            if tr and orig:
                lines.append(f"{orig}\n{tr}")
            else:
                lines.append(orig or tr)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _estimate_entry_duration(text: str, seconds_per_char: float) -> float:
        text_len = max(len((text or "").replace("\n", "").strip()), 1)
        estimated = text_len * seconds_per_char
        return max(0.6, min(estimated, 6.0))

    @classmethod
    def _repair_timestamps(cls, entries: List[Dict]) -> List[Dict]:
        """Repair invalid or missing timestamps while preserving sentence boundaries."""
        if not entries:
            return entries

        repaired = [dict(entry) for entry in entries]
        valid_durations = []
        chars_per_second_samples = []
        for entry in repaired:
            start = float(entry.get("start", 0) or 0)
            end = float(entry.get("end", 0) or 0)
            duration = end - start
            text = (entry.get("text") or entry.get("translated") or "").strip()
            if duration > 0:
                valid_durations.append(duration)
                text_len = max(len(text.replace("\n", "")), 1)
                chars_per_second_samples.append(duration / text_len)

        fallback_duration = median(valid_durations) if valid_durations else 1.8
        seconds_per_char = median(chars_per_second_samples) if chars_per_second_samples else 0.18

        next_valid_start_cache: Dict[int, Optional[float]] = {}
        next_valid_start = None
        for idx in range(len(repaired) - 1, -1, -1):
            entry = repaired[idx]
            start = float(entry.get("start", 0) or 0)
            end = float(entry.get("end", 0) or 0)
            if end > start and start >= 0:
                next_valid_start = start
            next_valid_start_cache[idx] = next_valid_start

        prev_end = 0.0
        for idx, entry in enumerate(repaired):
            start = float(entry.get("start", 0) or 0)
            end = float(entry.get("end", 0) or 0)
            text = (entry.get("text") or entry.get("translated") or "").strip()
            estimated_duration = cls._estimate_entry_duration(text, seconds_per_char) if text else fallback_duration
            next_start = next_valid_start_cache.get(idx + 1)

            has_valid_start = start >= 0
            has_valid_end = end > 0
            if not has_valid_start:
                start = prev_end

            if end <= start:
                if next_start is not None and next_start > prev_end:
                    start = max(start, prev_end)
                    end = min(start + estimated_duration, next_start)
                    if end <= start:
                        end = min(next_start, start + max(0.3, estimated_duration * 0.5))
                else:
                    start = max(start, prev_end)
                    end = start + estimated_duration
            else:
                start = max(start, prev_end)
                if end <= start:
                    end = start + estimated_duration

            if next_start is not None and next_start > start and end > next_start:
                end = next_start
                if end <= start:
                    end = start + max(0.3, min(estimated_duration, 0.8))

            entry["start"] = round(start, 3)
            entry["end"] = round(end, 3)
            prev_end = entry["end"]

        return repaired

    # ── 验证 ────────────────────────────────────────────────────────

    def validate_inputs(self, task_dir: str) -> bool:
        cache_dir = os.path.join(task_dir, "cache")
        return (
            find_artifact(cache_dir, "subtitle_aligned.json") is not None
            or find_artifact(cache_dir, "sentences.json") is not None
        )

    def check_artifact(self, task_dir: str) -> bool:
        node_cfg = getattr(self, "_node_config", {}) or {}
        file_prefix = str(node_cfg.get("file_prefix", "") or "").strip()
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        return os.path.exists(os.path.join(task_dir, "output", f"{file_prefix}subtitles{node_suffix}.srt"))

    # ── 主流程 ──────────────────────────────────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "解析上游字幕数据...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        entries, is_bilingual = self._resolve_input(task_dir, step_inputs)
        if not entries:
            raise RuntimeError("未找到有效的字幕输入数据（sentences.json / translation.json / subtitle_aligned.json）")

        source_lang, target_lang = self._resolve_languages_from_input(task_dir)

        if callback:
            callback(25, f"解析到 {len(entries)} 条字幕（{'双语' if is_bilingual else '单语'}）")

        if callback:
            callback(42, "校正字幕时间戳...")
        entries = self._repair_timestamps(entries)

        node_cfg = getattr(self, "_node_config", {}) or {}
        if node_cfg.get("filter_punctuation"):
            replace_mode = str(node_cfg.get("punctuation_replace_mode") or "space").strip().lower()
            if replace_mode not in {"space", "remove"}:
                replace_mode = "space"
            # 根据 processing_language 配置确定处理语言
            processing_lang = str(node_cfg.get("processing_language") or "from_source").strip().lower()
            if processing_lang == "from_source":
                filter_lang = source_lang
            elif processing_lang == "from_target":
                filter_lang = target_lang
            elif processing_lang and processing_lang != "from_source":
                filter_lang = processing_lang
            else:
                filter_lang = source_lang
            if callback:
                callback(46, f"按语言过滤字幕标点 ({filter_lang})...")
            entries = self._apply_punctuation_filter(
                entries,
                source_lang=filter_lang,
                target_lang=filter_lang,
                replace_mode=replace_mode,
            )

        # 创建输出目录
        output_dir = os.path.join(task_dir, "output")
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(output_dir, exist_ok=True)

        # 读取文件名前缀
        file_prefix = str(node_cfg.get("file_prefix", "") or "").strip()
        node_suffix = f"_{self._node_id}" if self._node_id else ""

        # 清理旧字幕，避免单语/双语切换时残留历史文件
        for rel_path in [
            os.path.join(output_dir, f"{file_prefix}subtitles{node_suffix}.srt"),
            os.path.join(output_dir, f"{file_prefix}subtitles_original{node_suffix}.srt"),
            os.path.join(output_dir, f"{file_prefix}subtitles_bilingual{node_suffix}.srt"),
            os.path.join(cache_dir, f"{file_prefix}subtitles.srt"),
            os.path.join(cache_dir, f"{file_prefix}subtitles_original.srt"),
            os.path.join(cache_dir, f"{file_prefix}subtitles_bilingual.srt"),
        ]:
            if os.path.exists(rel_path):
                os.remove(rel_path)

        artifacts = []
        count = 0
        outputs = {}

        if is_bilingual:
            # ── 双语模式 ──
            if callback:
                callback(50, "生成译文字幕...")
            srt_translated = self._entries_to_srt(entries, key="translated")
            path_tr = os.path.join(output_dir, f"{file_prefix}subtitles{node_suffix}.srt")
            with open(path_tr, "w", encoding="utf-8") as f:
                f.write(srt_translated)
            # cache 副本供 s07 使用
            with open(os.path.join(cache_dir, f"{file_prefix}subtitles.srt"), "w", encoding="utf-8") as f:
                f.write(srt_translated)
            artifacts.append(f"output/{file_prefix}subtitles{node_suffix}.srt")
            count = len(entries)

            if callback:
                callback(65, "生成原文字幕...")
            srt_original = self._entries_to_srt(entries, key="text")
            path_orig = os.path.join(output_dir, f"{file_prefix}subtitles_original{node_suffix}.srt")
            with open(path_orig, "w", encoding="utf-8") as f:
                f.write(srt_original)
            with open(os.path.join(cache_dir, f"{file_prefix}subtitles_original.srt"), "w", encoding="utf-8") as f:
                f.write(srt_original)
            artifacts.append(f"output/{file_prefix}subtitles_original{node_suffix}.srt")

            if callback:
                callback(80, "生成双语合并字幕...")
            srt_bilingual = self._entries_to_bilingual_srt(entries)
            path_bi = os.path.join(output_dir, f"{file_prefix}subtitles_bilingual{node_suffix}.srt")
            with open(path_bi, "w", encoding="utf-8") as f:
                f.write(srt_bilingual)
            with open(os.path.join(cache_dir, f"{file_prefix}subtitles_bilingual.srt"), "w", encoding="utf-8") as f:
                f.write(srt_bilingual)
            artifacts.append(f"output/{file_prefix}subtitles_bilingual{node_suffix}.srt")
            outputs = {
                "subtitle": f"output/{file_prefix}subtitles{node_suffix}.srt",
                "original": f"output/{file_prefix}subtitles_original{node_suffix}.srt",
                "bilingual": f"output/{file_prefix}subtitles_bilingual{node_suffix}.srt",
            }

        else:
            # ── 单语模式：只生成原文字幕 ──
            if callback:
                callback(60, "生成原文字幕...")
            srt_text = self._entries_to_srt(entries, key="text")
            path_srt = os.path.join(output_dir, f"{file_prefix}subtitles{node_suffix}.srt")
            with open(path_srt, "w", encoding="utf-8") as f:
                f.write(srt_text)
            with open(os.path.join(cache_dir, f"{file_prefix}subtitles.srt"), "w", encoding="utf-8") as f:
                f.write(srt_text)
            artifacts.append(f"output/{file_prefix}subtitles{node_suffix}.srt")
            count = len(entries)
            outputs = {
                "original": f"output/{file_prefix}subtitles{node_suffix}.srt",
            }

        if callback:
            callback(100, f"已生成 {count} 条字幕")

        return {
            "artifacts": artifacts,
            "outputs": outputs,
            "subtitle_count": count,
        }
