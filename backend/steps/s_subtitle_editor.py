"""s_subtitle_editor: 可视化编辑字幕的透传节点。

默认不修改输入字幕，直接按原名透传为输出；
用户在节点卡片点击「打开字幕编辑页」逐条编辑（文本/时间/合并/拆分）后，
结果存于节点配置 edited_subtitles（JSON 数组 [{start, end, text}]），
节点运行时据此输出：开启「另存副本」则生成带随机后缀的副本文件，否则覆盖原字幕文件。
输出格式跟随输入格式（.srt 写回 SRT，.json 写回 JSON）。
"""
import json
import os
import uuid
from typing import Callable, Optional

import pysubs2

from backend.steps.base_step import BaseStep


def _parse_srt(content: str) -> list:
    """使用成熟的 pysubs2 库解析字幕文本（支持 SRT/VTT/ASS），时间为秒。

    保留多行文本（含双语字幕），解析失败返回空列表。
    """
    try:
        subs = pysubs2.SSAFile.from_string(content)
    except Exception:
        return []
    return [
        {"start": line.start / 1000.0, "end": line.end / 1000.0, "text": line.text.replace("\\N", "\n")}
        for line in subs
    ]


def _pick_bilingual(item: dict) -> str:
    """从条目中提取文本，双语字幕（原文+译文）合并为两行。"""
    original = item.get("text", item.get("origin", item.get("original", item.get("src", item.get("content", "")))))
    translated = item.get("translation", item.get("translate", item.get("translated", item.get("tr", item.get("direct", item.get("reflect", ""))))))
    parts = [str(original or "").strip(), str(translated or "").strip()]
    parts = [p for p in parts if p]
    return "\n".join(parts) if parts else ""


def _normalize_entries(data) -> list:
    """Normalize various subtitle JSON shapes into [{start, end, text}]，保留双语（原文/译文两行）。"""
    if isinstance(data, dict):
        for key in ("segments", "items", "subtitles", "entries"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, list):
        return []
    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        start = item.get("start", item.get("begin", item.get("start_time")))
        end = item.get("end", item.get("end_time", item.get("finish")))
        if start is None or end is None:
            continue
        try:
            start_f, end_f = float(start), float(end)
        except (ValueError, TypeError):
            continue
        entries.append({"start": start_f, "end": end_f, "text": _pick_bilingual(item)})
    return entries


def _entries_to_srt(entries: list) -> str:
    subs = pysubs2.SSAFile()
    for e in entries:
        subs.append(pysubs2.SSAEvent(
            start=int(round(max(0, float(e.get("start", 0))) * 1000)),
            end=int(round(max(0, float(e.get("end", 0))) * 1000)),
            text=str(e.get("text", "")),
        ))
    return subs.to_string("srt")


def _load_subtitle_input(value, task_dir: str):
    """Return (entries, ext, source_path)."""
    if isinstance(value, (dict, list)):
        return _normalize_entries(value), "json", None
    raw = str(value)
    p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
    if os.path.isfile(p):
        ext = os.path.splitext(p)[1].lower() or ".srt"
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        if ext == ".json":
            return _normalize_entries(json.loads(content)), ext, p
        return _parse_srt(content), ext, p
    # 直接文本输入
    text = raw.strip()
    try:
        return _normalize_entries(json.loads(text)), ".json", None
    except Exception:
        return _parse_srt(text), ".srt", None


def _save_entries(entries: list, save_path: str, ext: str) -> None:
    if ext == ".json":
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    else:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(_entries_to_srt(entries))


class S_SubtitleEditor(BaseStep):
    step_id = "s_subtitle_editor"
    step_name = "字幕编辑"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return False  # 透传或覆盖原文件，无独立产物标记，始终执行

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        enable_copy = node_config.get("enable_copy", True)
        if isinstance(enable_copy, str):
            enable_copy = enable_copy.lower() in ("true", "1", "yes")
        edited = str(node_config.get("edited_subtitles", "") or "").strip()

        sub_input = step_inputs.get("subtitle", "")
        if not sub_input:
            raise ValueError("未连接字幕输入")

        entries, ext, source_path = _load_subtitle_input(sub_input, task_dir)

        # --- 未编辑：直接透传原文件（按原名） ---
        if not edited:
            if callback:
                callback(100, "未进行编辑，透传原字幕")
            if source_path:
                return {"artifacts": [], "outputs": {"subtitle": source_path}}
            output_dir = os.path.join(task_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"subtitle_edit_{node_id}{ext}")
            _save_entries(entries, out_path, ext)
            rel = f"output/subtitle_edit_{node_id}{ext}"
            return {"artifacts": [rel], "outputs": {"subtitle": rel}}

        # --- 已编辑：解析并保存 ---
        try:
            edited_entries = _normalize_entries(json.loads(edited))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("编辑后的字幕内容无效") from exc
        if not edited_entries:
            raise ValueError("编辑后的字幕内容为空")

        if callback:
            callback(60, "正在保存编辑后的字幕")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        if source_path and not enable_copy:
            # 不建副本：直接覆盖原文件（保持原格式）
            save_path = source_path
            save_ext = ext
        elif source_path:
            base = os.path.splitext(os.path.basename(source_path))[0]
            save_path = os.path.join(output_dir, f"{base}_{uuid.uuid4().hex[:8]}{ext}")
            save_ext = ext
        else:
            save_path = os.path.join(output_dir, f"subtitle_edit_{node_id}{ext}")
            save_ext = ext

        _save_entries(edited_entries, save_path, save_ext)

        rel_path = source_path if save_path == source_path else os.path.relpath(save_path, task_dir).replace("\\", "/")
        if callback:
            callback(100, f"已保存编辑结果到 {os.path.basename(rel_path)}")
        return {"artifacts": [rel_path], "outputs": {"subtitle": rel_path}}
