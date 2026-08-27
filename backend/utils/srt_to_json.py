# -*- coding: utf-8 -*-
"""SRT 字幕 -> 规范 segments JSON 转换工具。

统一输出格式：
{
  "segments": [
    {"id": 1, "text": "文本", "speaker": "", "start": 1.23, "end": 4.56},
    ...
  ]
}

供「按照字幕切割音频」等节点复用。
"""
import json
import os
import re


def _parse_timestamp(ts: str) -> float:
    """解析 SRT 时间戳 'HH:MM:SS,mmm' 或 'HH:MM:SS.mmm' 为秒。"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"无效的时间戳格式: {ts}")
    try:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, TypeError):
        raise ValueError(f"无法解析时间戳: {ts}")


def parse_srt(content: str) -> list:
    """解析 SRT 文本为 [{start, end, text}] 列表（时间单位为秒）。"""
    content = (content or "").strip()
    if not content:
        return []
    entries = []
    blocks = re.split(r"\n\s*\n", content)
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        # 找到时间轴行
        ts_line = None
        for ln in lines:
            if " --> " in ln:
                ts_line = ln
                break
        if not ts_line:
            continue
        start_str, end_str = ts_line.split(" --> ")
        start = _parse_timestamp(start_str)
        end = _parse_timestamp(end_str)
        idx = lines.index(ts_line) + 1
        text = "\n".join(lines[idx:]).strip()
        entries.append({"start": start, "end": end, "text": text})
    return entries


def srt_to_segments(srt_input: str) -> dict:
    """将 SRT（文件路径或原始文本）转换为规范的 segments 字典。

    返回 {"segments": [{"id": int, "text": str, "speaker": "", "start": float, "end": float}]}。

    - 若 srt_input 为已存在的文件路径则读取；
    - 否则当作 SRT 原始文本直接解析。
    """
    if os.path.isfile(srt_input):
        with open(srt_input, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = srt_input
    entries = parse_srt(content)
    segments = []
    for i, e in enumerate(entries, start=1):
        segments.append({
            "id": i,
            "text": e.get("text", ""),
            "speaker": "",
            "start": e["start"],
            "end": e["end"],
        })
    return {"segments": segments}


def srt_file_to_json_file(srt_path: str, out_path: str) -> str:
    """将 SRT 文件转换为 JSON 文件，返回输出路径。"""
    data = srt_to_segments(srt_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path
