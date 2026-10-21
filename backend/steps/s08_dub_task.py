"""s08_dub_task: Build a TTS task sheet from upstream timestamped sentence JSON."""
import json
import logging
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

from backend.config.config_manager import config
from backend.steps.base_step import BaseStep, find_artifact, step_check_cancel

logger = logging.getLogger(__name__)


class S08DubTask(BaseStep):
    step_id = "s08_dub_task"
    step_name = "生成配音任务"
    dependencies = ["s06_subtitle_gen"]

    # 语速预测缩减阈值：预测时长 > 时间槽时长 * ratio 且绝对差 > margin 秒时视为超长
    # ratio 取 2.0：后续 s09 调速步骤(max=1.5)可消化约一半余量，故此处仅在预测明显超长时才改文案
    SPEED_REDUCE_RATIO = 2.0
    SPEED_REDUCE_MIN_MARGIN = 0.5

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

    @staticmethod
    def _locate_file(value: str, task_dir: str) -> Optional[str]:
        """定位字符串对应的文件：先按绝对路径，再按相对 task_dir 解析。"""
        if not value:
            return None
        if os.path.isabs(value) and os.path.isfile(value):
            return value
        if task_dir:
            rel = os.path.join(task_dir, value)
            if os.path.isfile(rel):
                return rel
        return None

    @staticmethod
    def _looks_like_subtitle(content: str) -> bool:
        """启发式判断文本是否为字幕：含 ``-->`` 且带形如 00:00:01,000 的时间轴。

        用于识别无扩展名或扩展名不可靠的字幕文件/内联字幕内容，
        避免它们被当成纯文本按行拆句而丢失时间戳。
        """
        sample = (content or "")[:4000]
        if "-->" not in sample:
            return False
        return bool(re.search(r"\d{1,3}:\d{2}(?::\d{2})?\s*[,.]", sample))

    @classmethod
    def _resolve_payload(cls, value, task_dir: str) -> Tuple[List[Dict], bool]:
        """把「文件路径 / 字幕文本 / JSON 字符串 / 内存 JSON」统一解析为句子条目。

        判定顺序：
        1. dict / list：按上游 JSON 结构解析
        2. 命中文件（.json → JSON；.srt/.vtt 或内容形如字幕 → 保留时间戳；其余按纯文本）
        3. 非文件：先看是否内联字幕，再尝试 JSON，最后当纯文本按行拆句

        返回 ``(entries, bilingual)``；无法解析出内容时返回 ``([], False)``。
        """
        if isinstance(value, (dict, list)):
            return cls._load_entries_from_json(value)
        if not isinstance(value, str) or not value.strip():
            return [], False

        v = value.strip()
        path = cls._locate_file(v, task_dir)
        if path:
            lower = path.lower()
            if lower.endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    return cls._load_entries_from_json(json.load(f))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # 字幕文件：保留时间戳，双语时上行原文、下行译文
            if lower.endswith((".srt", ".vtt")) or cls._looks_like_subtitle(content):
                bilingual = cls._detect_bilingual_srt(content)
                entries = cls._parse_srt(content, bilingual)
                if entries:
                    return entries, bilingual
            return cls._load_entries_from_text(content)

        # 非文件输入：内联字幕内容 / 内联 JSON / 纯文本
        if cls._looks_like_subtitle(v):
            bilingual = cls._detect_bilingual_srt(v)
            entries = cls._parse_srt(v, bilingual)
            if entries:
                return entries, bilingual
        try:
            data = json.loads(v)
        except json.JSONDecodeError:
            return cls._load_entries_from_text(v)
        return cls._load_entries_from_json(data)

    @classmethod
    def _resolve_input(
        cls,
        task_dir: str,
        step_inputs: Optional[Dict] = None,
        node_cfg: Optional[Dict] = None,
    ) -> Tuple[List[Dict], bool]:
        """Resolve upstream input into sentence entries.

        输入优先级（SRT 字幕优先，保证时间戳不丢）：
        1. ``srt_file`` 连线端口 / 卡片 ``srt_path`` 配置：SRT 或 VTT 字幕
        2. ``subtitle`` / ``text`` 连线端口：句子时间戳 JSON，也兼容 SRT 路径或字幕内容
        3. ``text_file`` 连线端口：纯文本文件
        4. 上游缓存兜底：subtitle_aligned.json → sentences+translation → sentences.json
        """
        step_inputs = step_inputs or {}
        node_cfg = node_cfg or {}
        cache_dir = os.path.join(task_dir, "cache")

        # 1) SRT 字幕：连线端口优先于卡片配置
        for source, raw in (
            ("srt_file", step_inputs.get("srt_file")),
            ("srt_path", node_cfg.get("srt_path")),
        ):
            if not raw:
                continue
            entries, bilingual = cls._resolve_payload(raw, task_dir)
            if entries:
                logger.info(
                    "[DubTask] 使用 SRT 字幕输入(%s): %d 条, 双语=%s", source, len(entries), bilingual
                )
                return entries, bilingual

        # 2) 句子时间戳 JSON（兼容 ASR/翻译结果，也兼容 SRT 路径）
        subtitle_input = step_inputs.get("subtitle") or step_inputs.get("text")
        if subtitle_input:
            entries, bilingual = cls._resolve_payload(subtitle_input, task_dir)
            if entries:
                return entries, bilingual

        # 3) 文本文件端口
        text_file_input = step_inputs.get("text_file")
        if text_file_input:
            entries, bilingual = cls._resolve_payload(text_file_input, task_dir)
            if entries:
                return entries, bilingual

        # 4) 上游缓存兜底
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

        # 5) 最后兜底：字幕生成步骤产出的 SRT（双语自动识别）
        srt_path = find_artifact(cache_dir, "subtitles.srt")
        if srt_path:
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()
            bilingual = cls._detect_bilingual_srt(srt_content)
            entries = cls._parse_srt(srt_content, bilingual)
            if entries:
                logger.info("[DubTask] 回退使用字幕产物 %s: %d 条", srt_path, len(entries))
                return entries, bilingual

        return [], False

    @staticmethod
    def _srt_ts_to_seconds(value: str) -> float:
        """把 SRT/VTT 时间戳转为秒。

        支持 ``HH:MM:SS,mmm``（SRT 逗号）、``HH:MM:SS.mmm``（VTT 句点）
        以及省略小时的 ``MM:SS,mmm``；格式非法时抛 ValueError。
        """
        v = str(value or "").strip().replace(",", ".")
        if not v:
            raise ValueError("empty timestamp")
        parts = v.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, minutes, seconds = "0", parts[0], parts[1]
        else:
            raise ValueError(f"invalid timestamp: {value!r}")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    @staticmethod
    def _iter_subtitle_blocks(content: str):
        """把字幕文本切分为块，并去掉空块。

        统一 CRLF/CR 为 LF，使 Windows 保存的字幕与 Linux 一致；
        以一个或多个空行作为块分隔。
        """
        text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        for block in re.split(r"\n{2,}", text.strip()):
            lines = block.split("\n")
            # 去掉块首尾空行，但保留中间空行（双语字幕的多行文本依赖行序）
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
            if lines:
                yield lines

    @classmethod
    def _parse_srt(cls, srt_content: str, is_bilingual: bool = False) -> List[Dict]:
        """Parse SRT/VTT content into entries.

        兼容以下常见变体，避免单条脏数据导致整体解析失败：
        - CRLF / CR 换行
        - 缺失或带序号的块（序号行通过 ``-->`` 定位自动跳过）
        - VTT 的 ``WEBVTT`` 头、``NOTE``/``STYLE``/``REGION`` 块与时间轴定位参数
        - 仅 ``MM:SS,mmm`` 两段式时间戳

        Args:
            srt_content:字幕文本内容（SRT 或 VTT）
            is_bilingual: 若为 True，则每块两行文本视为双语（上行原文、下行译文）
        """
        entries: List[Dict] = []
        skipped = 0
        for lines in cls._iter_subtitle_blocks(srt_content):
            head = lines[0].strip()
            # 跳过 VTT 头部与元数据块
            if head.upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
                continue

            # 定位时间戳行：序号行是否存在都能正确处理
            ts_index = -1
            for i, line in enumerate(lines):
                if "-->" in line:
                    ts_index = i
                    break
            if ts_index < 0:
                skipped += 1
                continue

            start_raw, _, end_raw = lines[ts_index].partition("-->")
            # VTT 时间戳尾部可能带 align:start position:0% 之类的定位参数
            end_token = end_raw.strip().split()
            if not end_token:
                skipped += 1
                continue
            try:
                start = cls._srt_ts_to_seconds(start_raw)
                end = cls._srt_ts_to_seconds(end_token[0])
            except (ValueError, TypeError):
                skipped += 1
                continue

            text_lines = [line.strip() for line in lines[ts_index + 1:] if line.strip()]
            if not text_lines:
                skipped += 1
                continue

            entry = {
                "start": round(start, 4),
                "end": round(end, 4),
                "speaker": 0,
            }
            if is_bilingual and len(text_lines) >= 2:
                # 双语字幕：上行原文，下行译文作为朗读文本
                entry["text"] = text_lines[0]
                entry["translated"] = text_lines[1]
            else:
                entry["text"] = "\n".join(text_lines)

            entries.append(entry)

        if skipped:
            logger.warning("[DubTask] SRT 解析跳过 %d 个无效字幕块", skipped)
        return entries

    @classmethod
    def _detect_bilingual_srt(cls, srt_content: str) -> bool:
        """检测字幕是否为双语（多数块含 2 行及以上文本）。

        只抽样前 5 个有效块，降低个别块换行差异带来的误判。
        """
        blocks = [
            lines for lines in cls._iter_subtitle_blocks(srt_content)
            if not lines[0].strip().upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))
        ]
        if not blocks:
            return False

        sample = blocks[:5]
        bilingual_count = 0
        for lines in sample:
            ts_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
            if ts_index < 0:
                continue
            if len([line for line in lines[ts_index + 1:] if line.strip()]) >= 2:
                bilingual_count += 1

        # 过半样本块为多行文本才判定为双语
        return bilingual_count > len(sample) * 0.5

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
    def _normalize_speaker(raw) -> object:
        """归一化 speaker：
        - None / 空串 / "null" / "None" / 0 → 视为「未标注说话人」，返回 None
        - 其余（含 "SPEAKER_00" 等字符串标签或非零整数）→ 原样返回，作为映射键
        """
        if raw is None:
            return None
        if isinstance(raw, str):
            s = raw.strip()
            if s in ("", "null", "None", "0"):
                return None
            return s
        if isinstance(raw, (int, float)):
            if raw == 0:
                return None
            return raw
        return None

    @staticmethod
    def _check_min_sentence_duration(entries: List[Dict], threshold: float = 0.2) -> None:
        """执行前单句时长检测：若存在时长小于 threshold 秒的句子，直接抛出错误。

        文本类输入（start/end 为 None）无法计算时长，跳过不报。
        """
        bad = []
        for idx, entry in enumerate(entries, start=1):
            start = entry.get("start")
            end = entry.get("end")
            if start is None or end is None:
                continue
            try:
                duration = float(end) - float(start)
            except (TypeError, ValueError):
                continue
            if duration < threshold:
                text = str(entry.get("text", "")).strip().replace("\n", " ")
                text_excerpt = (text[:30] + "…") if len(text) > 31 else text
                bad.append((idx, round(duration, 3), text_excerpt))
        if bad:
            lines = "；".join(
                f"句子#{sid} 时长={dur}s" + (f"（文本：{t}）" if t else "")
                for sid, dur, t in bad
            )
            raise RuntimeError(
                f"检测到 {len(bad)} 条单句时长小于 {threshold} 秒，无法正常配音：{lines}"
            )

    @classmethod
    def _build_segments(cls, entries: List[Dict], task_dir: str = "") -> List[Dict]:
        """Build TTS segments from entries.

        将上游 speaker（可能为 "SPEAKER_00" 等字符串标签，或整数序号）稳定映射为
        整数 character_id：按首次出现顺序为每个不同说话人分配 0,1,2... 序号。

        Args:
            entries: List of sentence entries with timestamps
            task_dir: Task directory for creating dub_temp folder
        """
        # Create dub_temp directory if task_dir is provided
        if task_dir:
            dub_temp_dir = os.path.join(task_dir, "cache", "dub_temp")
            os.makedirs(dub_temp_dir, exist_ok=True)

        # 建立 说话人标签 -> 整数 character_id 的稳定映射（按出现顺序）
        speaker_map: Dict[object, int] = {}
        for entry in entries:
            spk = cls._normalize_speaker(entry.get("speaker", 0))
            if spk is not None and spk not in speaker_map:
                speaker_map[spk] = len(speaker_map)

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

            # speaker -> character_id：未标注说话人时用 0（单一角色）兜底
            spk = cls._normalize_speaker(entry.get("speaker", 0))
            character_id = speaker_map[spk] if spk is not None else 0

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
                "character_id": character_id,
                "read_character_id": character_id,
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

    # ═══════════ 语速预测 + 句子缩减（speed_predict_reduce） ═══════════

    @classmethod
    def _apply_speed_predict_reduction(
        cls,
        segments: List[Dict],
        read_language: str,
        node_cfg: Dict,
        callback: Optional[Callable] = None,
    ) -> Dict[str, int]:
        """语速预测缩减：预测每句 TTS 朗读时长，明显超过时间槽时由 LLM 缩减朗读文本。

        - 时长预测复用多语言估算模块 backend/utils/tts_duration_estimator（无需调用 TTS 引擎）
        - 缩减请求复用 s09 的字幕缩减实现（backend/utils/subtitle_reduction，含批次并发、
          短句跳过与缩减幅度校验），提示词模板沿用 s09_subtitle_reduction
        - 短句（中文<3字 / 英文等词类语言<2词）自动跳过缩减
        - 无时间戳输入（duration 为 None）无法比较，整体跳过

        Returns:
            统计信息 {"predicted": 预测句数, "overflow": 超长句数, "reduced": 实际缩减句数}
        """
        from backend.utils.tts_duration_estimator import estimate_tts_duration
        from backend.utils.subtitle_reduction import reduce_overflow_texts

        timed = [seg for seg in segments if seg.get("duration")]
        if not timed:
            logger.info("[DubTask] 语速预测缩减：输入无时间戳（文本配音模式），跳过")
            return {"predicted": 0, "overflow": 0, "reduced": 0}

        # 1) 多语言 TTS 时长预测
        for seg in timed:
            text = seg.get("read_text") or seg.get("text") or ""
            seg["tts_predicted_duration"] = estimate_tts_duration(text, read_language)

        # 2) 筛选超长句：预测时长远大于时间槽时长
        try:
            ratio = float(node_cfg.get("speed_predict_ratio") or cls.SPEED_REDUCE_RATIO)
        except (TypeError, ValueError):
            ratio = cls.SPEED_REDUCE_RATIO
        try:
            margin = float(node_cfg.get("speed_predict_margin") or cls.SPEED_REDUCE_MIN_MARGIN)
        except (TypeError, ValueError):
            margin = cls.SPEED_REDUCE_MIN_MARGIN

        overflow = []
        for seg in timed:
            predicted = seg.get("tts_predicted_duration") or 0.0
            duration = seg.get("duration") or 0.0
            if duration > 0 and predicted > duration * ratio and predicted - duration > margin:
                # 借用 real_duration 字段向共享缩减模块传递预测时长（用于计算目标缩减比例）
                seg["real_duration"] = predicted
                overflow.append(seg)

        stats = {"predicted": len(timed), "overflow": len(overflow), "reduced": 0}
        logger.info(
            f"[DubTask] 语速预测：共 {len(timed)} 句，超长 {len(overflow)} 句"
            f"（阈值：预测 > 时槽×{ratio:.2f} 且差值>{margin:.2f}s）"
        )

        if not overflow:
            return stats

        # 3) LLM 缩减（复用 s09 共享缩减实现，内部自动跳过短句）
        if callback:
            callback(80, f"语速预测：{len(overflow)}/{len(timed)} 句预测超长，调用 LLM 缩减...")
        try:
            stats["reduced"] = reduce_overflow_texts(
                overflow,
                step_name="s09_subtitle_reduction",
                log=lambda msg: logger.info(f"[DubTask] {msg}"),
            )
        except Exception as e:
            logger.warning(f"[DubTask] LLM 缩减异常（不中断任务）: {e}")
        finally:
            # 清理临时传递字段，避免泄漏到下游任务单
            for seg in overflow:
                seg.pop("real_duration", None)

        return stats

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
                    "tts_predicted_duration": seg.get("tts_predicted_duration"),
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

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "解析上游句子/字幕输入...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_cfg = getattr(self, "_node_config", {}) or {}
        entries, is_bilingual = self._resolve_input(task_dir, step_inputs, node_cfg)

        if not entries:
            # 兜底：字幕生成步骤产出的 SRT（双语自动识别）
            srt_path = find_artifact(os.path.join(task_dir, "cache"), "subtitles.srt")
            if srt_path and os.path.exists(srt_path):
                with open(srt_path, "r", encoding="utf-8") as f:
                    srt_content = f.read()
                is_bilingual = self._detect_bilingual_srt(srt_content)
                entries = self._parse_srt(srt_content, is_bilingual)

        if not entries:
            raise RuntimeError("未找到有效的句子时间戳/字幕输入数据")

        if callback:
            callback(25, f"解析到 {len(entries)} 条数据（{'双语' if is_bilingual else '单语'}）")

        # 执行前单句时长检测：任意单句时长小于阈值(秒)直接报错，阈值可由前端配置(默认0.2)
        min_dur_cfg = node_cfg.get("min_sentence_duration")
        try:
            threshold = float(min_dur_cfg) if min_dur_cfg not in (None, "") else 0.2
        except (TypeError, ValueError):
            threshold = 0.2
        self._check_min_sentence_duration(entries, threshold=threshold)

        read_language = self._resolve_read_language(task_dir)
        enable_tone = bool(node_cfg.get("ai_read_tone"))
        enable_normalize = bool(node_cfg.get("normalize_chinese_read_text"))
        enable_dialect = bool(node_cfg.get("ai_dialect_colloquial"))
        enable_speed_reduce = bool(node_cfg.get("speed_predict_reduce"))
        dialect_name = str(node_cfg.get("dialect_name") or "四川话").strip() or "四川话"

        logger.info(f"[DubTask] 节点配置: {node_cfg}")
        logger.info(
            f"[DubTask] LLM选项: ai_read_tone={enable_tone}, normalize={enable_normalize}, "
            f"dialect={enable_dialect}, speed_predict_reduce={enable_speed_reduce}"
        )

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

        # 语速预测缩减：预测 TTS 时长并对超长句调用 LLM 缩减（在写盘前完成，保证下游拿到缩减后文本）
        speed_reduce_stats = {"predicted": 0, "overflow": 0, "reduced": 0}
        if enable_speed_reduce:
            if callback:
                callback(72, "语速预测：估算各句 TTS 朗读时长...")
            # 72→100 之间是语速预测 LLM 批量（可数分钟），callback 间隙补取消检查点
            step_check_cancel(cancel_callback)
            try:
                speed_reduce_stats = self._apply_speed_predict_reduction(
                    segments, read_language, node_cfg, callback
                )
            except Exception as e:
                logger.warning(f"[DubTask] 语速预测缩减异常（不中断任务）: {e}")
                import traceback
                traceback.print_exc()

        self._write_csv(task_dir, segments)

        json_payload = self._build_json_payload(
            segments,
            read_language=read_language,
            options={
                "ai_read_tone": enable_tone,
                "normalize_chinese_read_text": enable_normalize and self._is_chinese_language(read_language),
                "ai_dialect_colloquial": enable_dialect,
                "dialect_name": dialect_name if enable_dialect else "",
                "speed_predict_reduce": enable_speed_reduce,
                "speed_reduce_predicted": speed_reduce_stats.get("predicted", 0),
                "speed_reduce_overflow": speed_reduce_stats.get("overflow", 0),
                "speed_reduce_count": speed_reduce_stats.get("reduced", 0),
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
        # 连线注入的输入（SRT 字幕端口 / 句子时间戳 JSON / 文本文件）也可作为入口
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        if (
            step_inputs.get("srt_file")
            or step_inputs.get("subtitle")
            or step_inputs.get("text")
            or step_inputs.get("text_file")
        ):
            return True
        # 卡片上直接指定的 SRT/VTT 字幕文件
        node_cfg = getattr(self, "_node_config", {}) or {}
        if str(node_cfg.get("srt_path") or "").strip():
            return True
        return bool(
            find_artifact(cache, "subtitle_aligned.json")
            or find_artifact(cache, "sentences.json")
            or find_artifact(cache, "subtitles.srt")
        )


StepDubTask = S08DubTask
