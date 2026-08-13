"""s08_dub_task: Build a TTS task sheet from upstream timestamped sentence JSON."""
import json
import logging
import os
from typing import Callable, Dict, List, Optional, Tuple

from backend.config.config_manager import config
from backend.steps.base_step import BaseStep, find_artifact

logger = logging.getLogger(__name__)


class S08DubTask(BaseStep):
    step_id = "s08_dub_task"
    step_name = "生成配音任务"
    dependencies = ["s06_subtitle_gen"]

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"cache/dub_task{node_suffix}.csv", f"cache/dub_task{node_suffix}.json"]

    @staticmethod
    def _load_entries_from_json(data) -> Tuple[List[Dict], bool]:
        """Load entries from upstream JSON payload.
        
        Read text priority: reflect > direct > text
        """
        if isinstance(data, dict):
            if isinstance(data.get("segments"), list):
                data = data["segments"]
            else:
                return [], False

        if not isinstance(data, list) or not data:
            return [], False

        first = data[0] if isinstance(data[0], dict) else {}

        if "src" in first or "tr" in first:
            entries = []
            for item in data:
                entry = {
                    "start": item.get("start", 0),
                    "end": item.get("end", item.get("start", 0) + 5),
                    "text": item.get("src") or item.get("text") or "",
                    "speaker": item.get("speaker", 0),
                }
                translated = item.get("tr") or item.get("translated") or ""
                if translated:
                    entry["translated"] = translated
                entries.append(entry)
            return entries, any("translated" in entry for entry in entries)

        entries = []
        bilingual = False
        for item in data:
            if not isinstance(item, dict):
                continue
            entry = {
                "start": item.get("start", 0),
                "end": item.get("end", item.get("start", 0) + 5),
                "text": item.get("text", item.get("src", "")),
                "speaker": item.get("speaker", 0),
            }
            # Read text priority: reflect > direct > text
            read_text = item.get("reflect") or item.get("direct") or item.get("text") or ""
            if read_text and read_text != entry["text"]:
                entry["translated"] = read_text
                bilingual = True
            entries.append(entry)
        return entries, bilingual

    @staticmethod
    def _load_entries_from_text(data) -> Tuple[List[Dict], bool]:
        """Load entries from a plain text payload.

        ``data`` 可以是已被读取的字符串，或包含 ``text`` 字段的字典。
        按换行符拆分为多条句子，没有的时间戳统一填为 null。
        """
        if isinstance(data, dict):
            data = data.get("text") or data.get("content") or ""

        lines = []
        for raw in str(data).split("\n"):
            line = raw.rstrip("\r").strip()
            if line:
                lines.append(line)

        entries = []
        for line in lines:
            entries.append({
                "start": None,
                "end": None,
                "text": line,
                "speaker": 0,
            })
        return entries, False

    @classmethod
    def _resolve_input(cls, task_dir: str, step_inputs: Optional[Dict] = None) -> Tuple[List[Dict], bool]:
        """Resolve upstream input into sentence entries.

        输入类型判断：
        - json 带时间戳的翻译文件 → 走原始处理模式
        - srt 字幕文件 → 解析时间戳
        - 文本文件（txt/md 等）→ 按换行拆分为多条句子，时间戳填 null
        """
        step_inputs = step_inputs or {}
        cache_dir = os.path.join(task_dir, "cache")

        subtitle_input = step_inputs.get("subtitle") or step_inputs.get("text")
        if subtitle_input:
            # 连线注入的路径可能是相对路径（相对 task_dir），需拼接到任务目录再判断
            if not os.path.isabs(subtitle_input):
                subtitle_input = os.path.join(task_dir, subtitle_input)
        if subtitle_input and os.path.exists(subtitle_input):
            lower = subtitle_input.lower()
            if lower.endswith(".json"):
                with open(subtitle_input, "r", encoding="utf-8") as f:
                    return cls._load_entries_from_json(json.load(f))
            if lower.endswith(".srt"):
                with open(subtitle_input, "r", encoding="utf-8") as f:
                    srt_content = f.read()
                    is_bilingual = cls._detect_bilingual_srt(srt_content)
                    return cls._parse_srt(srt_content, is_bilingual), is_bilingual
            # 文本类文件：按换行拆句，时间戳填 null
            with open(subtitle_input, "r", encoding="utf-8") as f:
                return cls._load_entries_from_text(f.read())

        text_file_input = step_inputs.get("text_file")
        if text_file_input:
            # 连线注入的路径可能是相对路径（相对 task_dir），需拼接到任务目录再判断
            if not os.path.isabs(text_file_input):
                text_file_input = os.path.join(task_dir, text_file_input)
            if os.path.exists(text_file_input):
                with open(text_file_input, "r", encoding="utf-8") as f:
                    return cls._load_entries_from_text(f.read())
            # 也可能直接传入文本内容
            return cls._load_entries_from_text(text_file_input)

        aligned_path = os.path.join(cache_dir, "subtitle_aligned.json")
        if os.path.exists(aligned_path):
            with open(aligned_path, "r", encoding="utf-8") as f:
                return cls._load_entries_from_json(json.load(f))

        sentences_path = os.path.join(cache_dir, "sentences.json")
        translation_path = os.path.join(cache_dir, "translation.json")
        if os.path.exists(sentences_path) and os.path.exists(translation_path):
            with open(sentences_path, "r", encoding="utf-8") as f:
                sentences = json.load(f)
            with open(translation_path, "r", encoding="utf-8") as f:
                translations = json.load(f)
            merged = []
            for index, sentence in enumerate(sentences):
                item = dict(sentence)
                if index < len(translations) and translations[index]:
                    item["translated"] = translations[index]
                merged.append(item)
            return cls._load_entries_from_json(merged)

        if os.path.exists(sentences_path):
            with open(sentences_path, "r", encoding="utf-8") as f:
                return cls._load_entries_from_json(json.load(f))

        return [], False

    @staticmethod
    def _parse_srt(srt_content: str, is_bilingual: bool = False) -> List[Dict]:
        """Parse SRT content into entries.
        
        Args:
            srt_content: SRT file content
            is_bilingual: If True, treat as bilingual subtitle (2nd line is translation)
        """
        entries = []
        for block in srt_content.strip().split("\n\n"):
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            ts = lines[1]
            start_s, end_s = ts.split(" --> ")

            def parse_t(value):
                value = value.strip().replace(",", ".")
                parts = value.split(":")
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

            text_lines = lines[2:]
            entry = {
                "start": parse_t(start_s),
                "end": parse_t(end_s),
                "speaker": 0,
            }
            
            if is_bilingual and len(text_lines) >= 2:
                # Bilingual subtitle: first line is original, second line is translation
                entry["text"] = text_lines[0].strip()
                entry["translated"] = text_lines[1].strip()
            else:
                # Single language subtitle
                entry["text"] = "\n".join(text_lines).strip()
            
            entries.append(entry)
        return entries

    @staticmethod
    def _detect_bilingual_srt(srt_content: str) -> bool:
        """Detect if SRT content is bilingual subtitle (has 2 lines of text per block)."""
        blocks = srt_content.strip().split("\n\n")
        if not blocks:
            return False
        
        # Check first few blocks to determine if bilingual
        bilingual_count = 0
        check_count = min(5, len(blocks))
        
        for block in blocks[:check_count]:
            lines = block.strip().split("\n")
            if len(lines) >= 4:  # index + timestamp + 2 text lines
                bilingual_count += 1
        
        # If majority of checked blocks have 2+ text lines, consider bilingual
        return bilingual_count > check_count * 0.5

    @staticmethod
    def _safe_language_code(value: str) -> str:
        value = str(value or "").strip().lower()
        if not value or value in {"auto", "from_input"}:
            return ""
        return value

    @classmethod
    def _resolve_read_language(cls, task_dir: str) -> str:
        task_json_path = os.path.join(task_dir, "task.json")
        if not os.path.exists(task_json_path):
            return ""
        try:
            with open(task_json_path, "r", encoding="utf-8") as f:
                task_info = json.load(f)
        except Exception:
            return ""

        input_cfg = task_info.get("input", {}) or {}
        target_language = cls._safe_language_code(input_cfg.get("target_language"))
        source_language = cls._safe_language_code(input_cfg.get("source_language"))
        return target_language or source_language

    @staticmethod
    def _is_chinese_language(language_code: str) -> bool:
        language_code = (language_code or "").lower()
        return language_code.startswith("zh") or language_code in {"cn", "chinese"}

    @staticmethod
    def _build_segments(entries: List[Dict], task_dir: str = "") -> List[Dict]:
        """Build TTS segments from entries.
        
        Args:
            entries: List of sentence entries with timestamps
            task_dir: Task directory for creating dub_temp folder
        """
        # Create dub_temp directory if task_dir is provided
        if task_dir:
            dub_temp_dir = os.path.join(task_dir, "cache", "dub_temp")
            os.makedirs(dub_temp_dir, exist_ok=True)
        
        segments = []
        for index, entry in enumerate(entries):
            original_text = entry.get("text", "")
            read_text = entry.get("translated") or original_text
            has_ts = entry.get("start") is not None and entry.get("end") is not None

            raw_gap = 0.0
            if has_ts and index < len(entries) - 1:
                next_start = entries[index + 1].get("start")
                if next_start is not None:
                    raw_gap = next_start - entry["end"]
                    if raw_gap < -0.001:
                        logger.warning(
                            "Dub segment %s overlaps next segment by %.3fs",
                            index,
                            abs(raw_gap),
                        )
            gap = max(0.0, raw_gap)

            start = round(entry["start"], 4) if has_ts else None
            end = round(entry["end"], 4) if has_ts else None
            duration = round(entry["end"] - entry["start"], 4) if has_ts else None
            segments.append({
                "index": index,
                "start": start,
                "end": end,
                "duration": duration,
                "original_duration": duration,
                "raw_gap_after": round(raw_gap, 4),
                "overlap_after": round(abs(raw_gap), 4) if raw_gap < 0 else 0.0,
                "gap_after": round(gap, 4),
                "speed_ratio": 1.0,
                "character_id": entry.get("speaker", 0),
                "read_character_id": entry.get("speaker", 0),
                "character_voice_desc": "",
                "text": original_text,
                "read_text": read_text,
                "read_tone_desc": "",
                "dialect": "",
                "方言": "",
                "audio_file": f"cache/dub_temp/{index:04d}.wav",
            })
        return segments

    @staticmethod
    def _build_llm_prompt(segments: List[Dict], enable_tone: bool, enable_normalize: bool, enable_dialect: bool, dialect_name: str, is_chinese: bool) -> dict:
        segment_payload = [
            {
                "index": seg["index"],
                "text": seg["text"],
                "read_text": seg["read_text"],
            }
            for seg in segments
        ]
        # Try to use JSON template via prompt service
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s08_dub_task", {
            "enable_tone": enable_tone,
            "enable_normalize": enable_normalize,
            "enable_dialect": enable_dialect,
            "dialect_name": dialect_name,
            "is_chinese": is_chinese,
            "segments": json.dumps(segment_payload, ensure_ascii=False, indent=2), # Keep JSON string for the default template
            "raw_segments": segment_payload, # Pass raw list for custom Jinja2 templates
        })
        if result.get("found"):
            return {
                "system_prompt": result.get("system_prompt") or "你是专业的 TTS 任务单整理助手，擅长中文文本归一化、朗读语气设计和方言口语化改写。",
                "user_prompt": result.get("user_prompt")
            }
        
        # Fallback to hardcoded prompt
        return {
            "system_prompt": "你是专业的 TTS 任务单整理助手，擅长中文文本归一化、朗读语气设计和方言口语化改写。",
            "user_prompt": json.dumps(
                {
                    "task": "根据配置一次性处理 TTS 任务单",
                    "requirements": {
                        "design_read_tone": enable_tone,
                        "normalize_chinese_read_text": enable_normalize and is_chinese,
                        "dialect_colloquial": enable_dialect,
                        "dialect_name": dialect_name if enable_dialect else "",
                        "target_language_is_chinese": is_chinese,
                    },
                    "rules": [
                        "仅返回 JSON 对象，顶层包含 segments 数组。",
                        "每个 segment 必须保留 index，并返回 read_text、read_tone_desc、方言 三个字段。",
                        "若未启用某功能，请保持原值或返回空字符串，不要编造额外字段。",
                        "朗读语气描述简短明确，控制在 12 个汉字以内。",
                        "中文归一化时，将数字、数值、日期、百分比、单位、货币、符号等改写为自然中文读法。",
                        "启用方言口语化时，在保留原意的前提下按目标方言改写 read_text，并在“方言”字段填写方言名称；未启用则填空字符串。",
                    ],
                    "segments": segment_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        }

    @classmethod
    def _resolve_llm_limits(cls, node_cfg: Dict) -> Tuple[int, int]:
        """Resolve LLM limits from global config.
        
        Priority: global config > default values
        """
        max_request_chars = int(config.get("llm.max_request_chars") or 12000)
        max_concurrent = int(config.get("llm.max_concurrent") or 10)
        return max(1000, max_request_chars), max(1, max_concurrent)

    @staticmethod
    def _estimate_segment_payload_chars(segment: Dict) -> int:
        return len(json.dumps({
            "index": segment["index"],
            "text": segment["text"],
            "read_text": segment["read_text"],
        }, ensure_ascii=False))

    @classmethod
    def _split_segments_for_llm(
        cls,
        segments: List[Dict],
        enable_tone: bool,
        enable_normalize: bool,
        enable_dialect: bool,
        dialect_name: str,
        is_chinese: bool,
        max_request_chars: int,
    ) -> List[List[Dict]]:
        prompt_data = cls._build_llm_prompt(
            [],
            enable_tone=enable_tone,
            enable_normalize=enable_normalize,
            enable_dialect=enable_dialect,
            dialect_name=dialect_name,
            is_chinese=is_chinese,
        )
        prompt_overhead = len(prompt_data["user_prompt"]) + len(prompt_data["system_prompt"])
        payload_budget = max(600, max_request_chars - prompt_overhead - 200)

        batches: List[List[Dict]] = []
        current_batch: List[Dict] = []
        current_chars = 0

        for segment in segments:
            segment_chars = cls._estimate_segment_payload_chars(segment)
            if current_batch and current_chars + segment_chars > payload_budget:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(segment)
            current_chars += segment_chars

        if current_batch:
            batches.append(current_batch)

        return batches

    @staticmethod
    def _apply_llm_updates_to_segments(
        segments: List[Dict],
        updates: Dict[int, Dict],
        enable_tone: bool,
        enable_normalize: bool,
        enable_dialect: bool,
        dialect_name: str,
    ) -> None:
        for seg in segments:
            update = updates.get(seg["index"])
            if not update:
                continue

            if enable_tone:
                seg["read_tone_desc"] = str(update.get("read_tone_desc", seg["read_tone_desc"]) or "").strip()

            if enable_dialect:
                dialect_value = str(update.get("方言") or dialect_name).strip() or dialect_name
                seg["方言"] = dialect_value
                seg["dialect"] = dialect_value
            else:
                seg["方言"] = ""
                seg["dialect"] = ""

            if enable_normalize or enable_dialect:
                next_read_text = str(update.get("read_text", seg["read_text"]) or "").strip()
                if next_read_text:
                    seg["read_text"] = next_read_text

    @classmethod
    def _apply_llm_enhancements(
        cls,
        segments: List[Dict],
        enable_tone: bool,
        enable_normalize: bool,
        enable_dialect: bool,
        dialect_name: str,
        read_language: str,
        node_cfg: Dict,
        callback: Optional[Callable] = None,
    ) -> Dict[str, int]:
        if not (enable_tone or enable_normalize or enable_dialect):
            return {"batch_count": 0, "max_request_chars": 0, "max_concurrent": 0}

        from backend.llm.llm_client import get_llm_client

        is_chinese = cls._is_chinese_language(read_language)
        max_request_chars, max_concurrent = cls._resolve_llm_limits(node_cfg)
        batches = cls._split_segments_for_llm(
            segments,
            enable_tone=enable_tone,
            enable_normalize=enable_normalize,
            enable_dialect=enable_dialect,
            dialect_name=dialect_name,
            is_chinese=is_chinese,
            max_request_chars=max_request_chars,
        )
        if callback:
            callback(65, f"按 {max_request_chars} 字阈值拆分为 {len(batches)} 批，最多并发 {max_concurrent} 路 LLM 请求...")

        requests = []
        for batch in batches:
            prompt_data = cls._build_llm_prompt(
                batch,
                enable_tone=enable_tone,
                enable_normalize=enable_normalize,
                enable_dialect=enable_dialect,
                dialect_name=dialect_name,
                is_chinese=is_chinese,
            )
            requests.append({
                "step_name": "s08_dub_task",
                "prompt": prompt_data["user_prompt"],
                "system_prompt": prompt_data["system_prompt"],
                "response_json": True,
                "log": True,
            })
        results = get_llm_client().batch_chat(requests, max_workers=max_concurrent)

        updates_by_index: Dict[int, Dict] = {}
        for batch_index, result in enumerate(results):
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(f"第 {batch_index + 1} 批 LLM 请求失败：{result['error']}")

            llm_segments = result.get("segments") if isinstance(result, dict) else None
            if not isinstance(llm_segments, list):
                raise RuntimeError(f"第 {batch_index + 1} 批 LLM 未返回有效的 segments 列表")

            for item in llm_segments:
                if isinstance(item, dict) and item.get("index") is not None:
                    updates_by_index[int(item["index"])] = item

        cls._apply_llm_updates_to_segments(
            segments,
            updates_by_index,
            enable_tone=enable_tone,
            enable_normalize=enable_normalize,
            enable_dialect=enable_dialect,
            dialect_name=dialect_name,
        )
        return {
            "batch_count": len(batches),
            "max_request_chars": max_request_chars,
            "max_concurrent": max_concurrent,
        }

    def _write_csv(self, task_dir: str, segments: List[Dict]) -> None:
        import pandas as pd

        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        csv_columns = [
            "index",
            "start",
            "end",
            "duration",
            "raw_gap_after",
            "overlap_after",
            "gap_after",
            "character_id",
            "read_character_id",
            "text",
            "read_text",
            "read_tone_desc",
            "方言",
            "audio_file",
        ]
        df = pd.DataFrame(segments)
        for column in csv_columns:
            if column not in df.columns:
                df[column] = ""
        df = df[csv_columns]
        csv_path = os.path.join(task_dir, "cache", f"dub_task{node_suffix}.csv")
        
        # Try to write with retry on permission error
        import time
        for attempt in range(3):
            try:
                df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                return
            except PermissionError:
                if attempt < 2:
                    print(f"[DubTask] CSV文件被占用，1秒后重试...")
                    time.sleep(1)
                else:
                    # Write to a backup location
                    backup_path = csv_path + ".bak"
                    print(f"[DubTask] 无法写入 {csv_path}，尝试写入备份 {backup_path}")
                    df.to_csv(backup_path, index=False, encoding="utf-8-sig")

    @staticmethod
    def _build_json_payload(segments: List[Dict], read_language: str, options: Dict[str, object]) -> Dict[str, object]:
        return {
            "segments": [
                {
                    "index": seg["index"],
                    "text": seg["text"],
                    "read_text": seg["read_text"],
                    "read_tone_desc": seg["read_tone_desc"],
                    "start": seg["start"],
                    "end": seg["end"],
                    "duration": seg["duration"],
                    "original_duration": seg["original_duration"],
                    "raw_gap_after": seg.get("raw_gap_after", seg.get("gap_after", 0.0)),
                    "overlap_after": seg.get("overlap_after", 0.0),
                    "gap_after": seg["gap_after"],
                    "speed_ratio": seg["speed_ratio"],
                    "audio_file": seg["audio_file"],
                    "character_id": seg["character_id"],
                    "read_character_id": seg["read_character_id"],
                    "character_voice_desc": seg["character_voice_desc"],
                    "dialect": seg["dialect"],
                    "方言": seg["方言"],
                }
                for seg in segments
            ],
            "total_segments": len(segments),
            "read_language": read_language,
            "options": options,
        }

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "解析上游句子时间戳 JSON...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        entries, is_bilingual = self._resolve_input(task_dir, step_inputs)

        if not entries:
            srt_path = find_artifact(os.path.join(task_dir, "cache"), "subtitles.srt")
            if srt_path and os.path.exists(srt_path):
                with open(srt_path, "r", encoding="utf-8") as f:
                    entries = self._parse_srt(f.read())
                is_bilingual = False

        if not entries:
            raise RuntimeError("未找到有效的句子时间戳输入数据")

        if callback:
            callback(25, f"解析到 {len(entries)} 条数据（{'双语' if is_bilingual else '单语'}）")

        node_cfg = getattr(self, "_node_config", {}) or {}
        read_language = self._resolve_read_language(task_dir)
        enable_tone = bool(node_cfg.get("ai_read_tone"))
        enable_normalize = bool(node_cfg.get("normalize_chinese_read_text"))
        enable_dialect = bool(node_cfg.get("ai_dialect_colloquial"))
        dialect_name = str(node_cfg.get("dialect_name") or "四川话").strip() or "四川话"

        logger.info(f"[DubTask] 节点配置: {node_cfg}")
        logger.info(f"[DubTask] LLM选项: ai_read_tone={enable_tone}, normalize={enable_normalize}, dialect={enable_dialect}")

        segments = self._build_segments(entries, task_dir)

        if callback:
            callback(45, "生成基础 TTS 任务单...")

        llm_runtime = {"batch_count": 0, "max_request_chars": 0, "max_concurrent": 0}
        if enable_tone or enable_normalize or enable_dialect:
            if callback:
                callback(60, "准备按字数阈值分批并并发请求 LLM 处理朗读语气/文本归一化/方言口语化...")
            llm_runtime = self._apply_llm_enhancements(
                segments,
                enable_tone=enable_tone,
                enable_normalize=enable_normalize,
                enable_dialect=enable_dialect,
                dialect_name=dialect_name,
                read_language=read_language,
                node_cfg=node_cfg,
                callback=callback,
            )

        self._write_csv(task_dir, segments)

        json_payload = self._build_json_payload(
            segments,
            read_language=read_language,
            options={
                "ai_read_tone": enable_tone,
                "normalize_chinese_read_text": enable_normalize and self._is_chinese_language(read_language),
                "ai_dialect_colloquial": enable_dialect,
                "dialect_name": dialect_name if enable_dialect else "",
                "llm_batch_count": llm_runtime["batch_count"],
                "llm_max_request_chars": llm_runtime["max_request_chars"],
                "llm_max_concurrent": llm_runtime["max_concurrent"],
            },
        )
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        json_path = os.path.join(task_dir, "cache", f"dub_task{node_suffix}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_payload, f, ensure_ascii=False, indent=2)
        except PermissionError:
            backup_path = json_path + ".bak"
            print(f"[DubTask] 无法写入 {json_path}，尝试写入备份 {backup_path}")
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(json_payload, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"生成 {len(segments)} 条 TTS 任务")

        return {
            "artifacts": [f"cache/dub_task{node_suffix}.csv", f"cache/dub_task{node_suffix}.json"],
            "outputs": {
                "text": f"cache/dub_task{node_suffix}.json",
                "pandas": f"cache/dub_task{node_suffix}.csv",
            },
            "total_segments": len(segments),
        }

    def check_artifact(self, task_dir: str) -> bool:
        cache = os.path.join(task_dir, "cache")
        return bool(
            find_artifact(cache, "dub_task.json")
            and find_artifact(cache, "dub_task.csv")
        )

    def validate_inputs(self, task_dir: str) -> bool:
        cache = os.path.join(task_dir, "cache")
        # 连线注入的输入（句子时间戳 JSON 或文本文件）也可作为入口
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        if step_inputs.get("subtitle") or step_inputs.get("text") or step_inputs.get("text_file"):
            return True
        return bool(
            find_artifact(cache, "subtitle_aligned.json")
            or find_artifact(cache, "sentences.json")
            or find_artifact(cache, "subtitles.srt")
        )


StepDubTask = S08DubTask
