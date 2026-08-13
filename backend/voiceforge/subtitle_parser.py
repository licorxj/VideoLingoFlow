"""SRT / ASS / VTT 字幕解析（移植自 LcVoiceForgeaApp.parsers.subtitle_parser 的核心逻辑）。"""
import re


def detect_subtitle_format(text: str):
    head = (text or "").strip()
    if head.startswith("WEBVTT"):
        return "vtt"
    if "[Script Info]" in head or "[V4+ Styles]" in head or "[V4 Styles]" in head:
        return "ass"
    if re.match(r"^\d+\s*\n\d{1,2}:\d{2}:\d{2}[,.]\d{3}", head):
        return "srt"
    return None


def _srt_ms(h, m, s, ms):
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def _clean_text(value: str):
    value = re.sub(r"<[^>]+>", "", value or "")
    value = value.replace("\\N", "\n").replace("\\n", "\n")
    return value.strip()


def parse_srt(content: str):
    entries = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or not re.match(r"^\d+$", lines[0]):
            continue
        time_line = next((line for line in lines[1:] if "-->" in line), None)
        if not time_line:
            continue
        match = re.match(
            r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})",
            time_line,
        )
        if not match:
            continue
        text = _clean_text("\n".join(line for line in lines[1:] if "-->" not in line))
        if text:
            entries.append(
                {
                    "index": len(entries) + 1,
                    "text": text,
                    "speaker": None,
                    "start_ms": _srt_ms(*match.group(1, 2, 3, 4)),
                    "end_ms": _srt_ms(*match.group(5, 6, 7, 8)),
                }
            )
    return entries


def parse_vtt(content: str):
    entries = []
    lines = content.splitlines()
    index = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("WEBVTT") or stripped.startswith("NOTE") or stripped.startswith("Kind:") or stripped.startswith("Language:"):
            continue
        if "-->" in stripped:
            match = re.match(
                r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})",
                stripped,
            )
            if not match:
                match = re.match(
                    r"(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2})[,.](\d{3})",
                    stripped,
                )
            if match:
                if len(match.groups()) == 8:
                    start = _srt_ms(*match.group(1, 2, 3, 4))
                    end = _srt_ms(*match.group(5, 6, 7, 8))
                else:
                    start = int(match.group(1)) * 60000 + int(match.group(2)) * 1000 + int(match.group(3))
                    end = int(match.group(4)) * 60000 + int(match.group(5)) * 1000 + int(match.group(6))
                index += 1
                entries.append({"index": index, "text": "", "speaker": None, "start_ms": start, "end_ms": end})
                continue
        if entries:
            text = _clean_text(stripped)
            if text:
                entries[-1]["text"] = (entries[-1]["text"] + "\n" + text).strip()
    return [entry for entry in entries if entry["text"]]


def parse_ass(content: str):
    entries = []
    format_fields = None
    in_events = False
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("Format:"):
            format_fields = [field.strip() for field in line[len("Format:"):].split(",")]
            continue
        if line.startswith("Dialogue:"):
            if not format_fields:
                continue
            payload = line[len("Dialogue:"):].strip()
            parts = payload.split(",", len(format_fields) - 1)
            if len(parts) != len(format_fields):
                continue
            fields = dict(zip(format_fields, parts))
            start = fields.get("Start", "")
            end = fields.get("End", "")
            speaker = fields.get("Name", "") or None
            text = _clean_text(fields.get("Text", ""))
            start_ms = _ass_ms(start)
            end_ms = _ass_ms(end)
            if text:
                entries.append({"index": len(entries) + 1, "text": text, "speaker": speaker, "start_ms": start_ms, "end_ms": end_ms})
        elif line.startswith("[") and not line.startswith("[" + "Events"):
            in_events = False
        elif line == "[Events]":
            in_events = True
    return entries


def _ass_ms(value: str):
    match = re.match(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,2})", value or "")
    if not match:
        return 0
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
    fraction = match.group(4)
    centi = int(fraction) * 10 if len(fraction) == 2 else int(fraction) * 100
    return hours * 3600000 + minutes * 60000 + seconds * 1000 + centi


def parse_subtitle(content: str):
    """按内容自动识别格式并解析，返回 entries 列表。格式不支持时抛出 ValueError。"""
    fmt = detect_subtitle_format(content)
    if fmt == "srt":
        return parse_srt(content)
    if fmt == "vtt":
        return parse_vtt(content)
    if fmt == "ass":
        return parse_ass(content)
    raise ValueError("不支持的字幕格式，仅支持 SRT / ASS / VTT")
