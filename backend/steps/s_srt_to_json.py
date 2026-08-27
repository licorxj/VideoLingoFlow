# -*- coding: utf-8 -*-
"""SRT 字幕转 ASR 结果格式 JSON 节点。

将 SRT 字幕转换为 ASR 结果格式 JSON（兼容下游预处理 / ASR 结果校验等节点）：

    {
        "language": "und",
        "text": "<用空格拼接的完整全文>",
        "segments": [
            {"id": 0, "start": 1.23, "end": 4.56, "text": "..."},
            ...
        ]
    }

不含词级时间戳（words）。"language" 设为 "und"（未定），由下游自行检测。
"""
import os
import json

from backend.steps.base_step import BaseStep
from backend.utils.srt_to_json import parse_srt


class S_SrtToJson(BaseStep):
    step_id = "srt_to_json"

    def check_artifact(self, task_dir):
        node_id = getattr(self, "_node_id", "")
        name = f"srt_to_json_{node_id}.json" if node_id else "srt_to_json.json"
        return os.path.isfile(os.path.join(task_dir, "cache", name))

    def validate_inputs(self, task_dir):
        raw = (getattr(self, "_step_inputs", {}) or {}).get("subtitle")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        path = raw if isinstance(raw, str) else None
        return bool(path) and os.path.isfile(path)

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        raw = (getattr(self, "_step_inputs", {}) or {}).get("subtitle")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        srt_path = raw if isinstance(raw, str) else None
        if not srt_path or not os.path.isfile(srt_path):
            raise ValueError(
                "SRT 转 JSON 失败：未提供有效的字幕文件路径（step_inputs['subtitle'] 为空或文件不存在）"
            )

        if callback:
            callback(10, f"读取 SRT：{os.path.basename(srt_path)}")
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        entries = parse_srt(content)
        if not entries:
            raise ValueError("SRT 转 JSON 失败：未解析到任何字幕条目，请检查 SRT 格式是否正确")

        segments = []
        for i, e in enumerate(entries):
            text = (e.get("text") or "").replace("\r", "").replace("\n", " ").strip()
            segments.append({
                "id": i,
                "start": e["start"],
                "end": e["end"],
                "text": text,
            })

        full_text = " ".join(seg["text"] for seg in segments)
        asr_result = {
            "language": "und",
            "text": full_text,
            "segments": segments,
        }

        if callback:
            callback(70, f"已转换 {len(segments)} 条字幕，写入 JSON ...")
        out_name = f"srt_to_json_{node_id}.json" if node_id else "srt_to_json.json"
        out_path = os.path.join(cache_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(asr_result, f, ensure_ascii=False, indent=2)

        self.artifacts = [os.path.join("cache", out_name)]
        if callback:
            callback(100, f"SRT 转 JSON 完成：{len(segments)} 条字幕")
        return {
            "artifacts": self.artifacts,
            "outputs": {"json": os.path.join("cache", out_name)},
        }
