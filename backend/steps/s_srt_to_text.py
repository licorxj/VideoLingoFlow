# -*- coding: utf-8 -*-
"""SRT 字幕转纯文本节点。

将 SRT 字幕直接转换为纯文本：去掉序号与时间轴，提取每条字幕的文本内容，
按原顺序拼接为 .txt 文本文件输出（保留字幕原有的多行文本结构）。
"""
import os

from backend.steps.base_step import BaseStep
from backend.utils.srt_to_json import parse_srt


class S_SrtToText(BaseStep):
    step_id = "srt_to_text"

    def check_artifact(self, task_dir):
        node_id = getattr(self, "_node_id", "")
        name = f"srt_to_text_{node_id}.txt" if node_id else "srt_to_text.txt"
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
                "SRT 转文本失败：未提供有效的字幕文件路径（step_inputs['subtitle'] 为空或文件不存在）"
            )

        if callback:
            callback(10, f"读取 SRT：{os.path.basename(srt_path)}")
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        entries = parse_srt(content)
        if not entries:
            raise ValueError("SRT 转文本失败：未解析到任何字幕条目，请检查 SRT 格式是否正确")

        # 去掉序号与时间轴，仅保留每条字幕的文本，按原顺序拼接（块间空行）
        blocks = [e.get("text", "").strip() for e in entries]
        blocks = [b for b in blocks if b]
        full_text = "\n\n".join(blocks)

        if callback:
            callback(70, f"已提取 {len(entries)} 条字幕文本，写入 .txt ...")
        out_name = f"srt_to_text_{node_id}.txt" if node_id else "srt_to_text.txt"
        out_path = os.path.join(cache_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        self.artifacts = [os.path.join("cache", out_name)]
        if callback:
            callback(100, f"SRT 转文本完成：{len(entries)} 条字幕")
        return {
            "artifacts": self.artifacts,
            "outputs": {"text": os.path.join("cache", out_name)},
        }
