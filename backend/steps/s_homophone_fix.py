"""s_homophone_fix: 中文同音字修复节点。

对字幕（SRT）或 ASR 结果 JSON 中的文本做**同音字修复**：按术语表的拼音匹配，
把 ASR 常见的同音错字替换为正确写法（如"比例比例"→"哔哩哔哩"、"悬界"→"玄戒"）。

* 纯 CPU、无模型、无网络（pypinyin + 术语表）
* **等长替换**：不改变文本长度，word 级时间戳与字幕行结构保持不变
* 术语来源：项目根 `自定义术语表.json` + 指定术语文件 + 节点内直接填写
"""
import json
import os
import re
from typing import Callable, List, Optional

from backend.steps.base_step import BaseStep
from backend.utils.homophone_fixer import HomophoneFixer, load_terms

_AUDIO_EXT_HINT = (".json", ".srt", ".txt")


def _fmt_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SHomophoneFix(BaseStep):
    step_id = "s_homophone_fix"
    step_name = "同音字修复"
    dependencies = []

    @property
    def artifacts(self):
        suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/homophone_fixed{suffix}.json",
                f"output/homophone_fixed{suffix}.srt"]

    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        out_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(out_dir):
            return False
        suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return any(name.startswith(f"homophone_fixed{suffix}") for name in os.listdir(out_dir))

    @staticmethod
    def _resolve_input_file(raw, task_dir: str) -> Optional[str]:
        items = raw if isinstance(raw, list) else [raw]
        for it in items:
            p = None
            if isinstance(it, str):
                p = it.strip()
            elif isinstance(it, dict):
                for k in ("path", "file", "filepath", "output"):
                    if isinstance(it.get(k), str):
                        p = it[k].strip()
                        break
            if not p:
                continue
            if os.path.isabs(p) and os.path.isfile(p):
                return p
            if task_dir:
                rp = os.path.join(task_dir, p)
                if os.path.isfile(rp):
                    return rp
        return None

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = (step_inputs.get("json") or step_inputs.get("subtitle")
               or step_inputs.get("any") or step_inputs.get("file"))
        # 内存数据（dict / list）直接视为有效输入
        if isinstance(raw, (dict, list)):
            return True
        if self._resolve_input_file(raw, task_dir):
            return True
        # 回退：扫描 cache/output 里的 json / srt 产物
        for sub in ("cache", "output"):
            d = os.path.join(task_dir, sub)
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if name.endswith((".json", ".srt")):
                    return True
        return False

    def _resolve_input_data(self, raw, task_dir: str) -> dict:
        """把字幕/ASR 输入解析为 {'segments': [...]} 结构。

        兼容：内存 dict / list、.json / .srt 文件路径（绝对或相对 task_dir）、
        内联 JSON 字符串、内联 SRT 文本。
        """
        if raw is None:
            path = self._scan_fallback_input(task_dir)
            if not path:
                raise ValueError("未收到有效的字幕/ASR JSON 输入（支持 .json / .srt）")
            return self._read_input_path(path)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            return {"segments": raw}
        if isinstance(raw, str):
            v = raw.strip()
            candidates = []
            if os.path.isabs(v) and os.path.isfile(v):
                candidates.append(v)
            if task_dir and os.path.isfile(os.path.join(task_dir, v)):
                candidates.append(os.path.join(task_dir, v))
            if candidates:
                return self._read_input_path(candidates[0])
            # 内联：先试 JSON，失败再按 SRT 文本解析
            try:
                data = json.loads(v)
            except json.JSONDecodeError:
                return {"segments": self._parse_srt(v), "language": "zh"}
            if isinstance(data, list):
                data = {"segments": data}
            return data
        raise ValueError("无法识别的字幕/ASR 输入（需 JSON / SRT 文件或数据）")

    @staticmethod
    def _read_input_path(path: str) -> dict:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        if path.lower().endswith(".srt"):
            return {"segments": SHomophoneFix._parse_srt(content), "language": "zh"}
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"输入 JSON 解析失败：{exc}") from exc
        if isinstance(data, list):
            data = {"segments": data}
        return data

    # ------------------------------------------------------------------
    @staticmethod
    def _scan_fallback_input(task_dir: str) -> Optional[str]:
        for sub in ("cache", "output"):
            d = os.path.join(task_dir, sub)
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if name.endswith(".json") and "homophone" not in name:
                    return os.path.join(d, name)
        for sub in ("cache", "output"):
            d = os.path.join(task_dir, sub)
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if name.endswith(".srt"):
                    return os.path.join(d, name)
        return None

    @staticmethod
    def _parse_srt(content: str) -> List[dict]:
        from backend.utils.srt_to_json import parse_srt
        return parse_srt(content)

    @staticmethod
    def _to_srt(segments: List[dict]) -> str:
        blocks = []
        for i, seg in enumerate(segments, 1):
            blocks.append(
                f"{i}\n{_fmt_ts(seg.get('start', 0))} --> {_fmt_ts(seg.get('end', 0))}\n"
                f"{(seg.get('text') or '').strip()}\n"
            )
        return "\n".join(blocks)

    # ------------------------------------------------------------------
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        raw = (step_inputs.get("json") or step_inputs.get("subtitle")
               or step_inputs.get("any") or step_inputs.get("file"))
        data = self._resolve_input_data(raw, task_dir)

        if callback:
            callback(5, "读取输入完成")

        segments = data.get("segments") or []
        if not segments:
            raise ValueError("输入 JSON 中没有 segments（需要 ASR 结果或字幕 segments 结构）")

        # ---- 术语表与修复器 ----
        include_project = node_config.get("include_project_glossary", True)
        if isinstance(include_project, str):
            include_project = include_project.lower() not in ("false", "0", "no")
        terms = load_terms(
            include_project_glossary=bool(include_project),
            terms_file=(node_config.get("terms_file") or "").strip() or None,
            extra_terms=node_config.get("extra_terms") or "",
        )
        min_len = int(node_config.get("min_len", 2) or 2)
        fuzzy = str(node_config.get("fuzzy", "strict")).lower() in ("fuzzy", "loose", "true", "1")
        if not terms:
            raise ValueError(
                "术语表为空：请在项目根 自定义术语表.json 添加术语，或在节点里填写“额外术语”")

        fixer = HomophoneFixer(terms, fuzzy=fuzzy, min_len=min_len)
        if callback:
            callback(20, f"术语 {len(fixer.terms)} 条（模糊音={'开' if fuzzy else '关'}）")

        # ---- 逐段修复 ----
        total_replace = 0
        hit_counter: dict = {}
        n = len(segments)
        for idx, seg in enumerate(segments):
            if cancel_callback and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError
                raise TaskCancelledError("Cancelled by user")
            if not isinstance(seg, dict):
                continue
            cnt, hits = fixer.fix_segment(seg)
            if cnt:
                total_replace += cnt
                for h in hits:
                    hit_counter[h] = hit_counter.get(h, 0) + 1
            if callback and n > 0:
                callback(20 + int(60 * (idx + 1) / n), f"修复 {idx + 1}/{n} 段")

        # ---- 落盘 ----
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""

        json_name = f"homophone_fixed{node_suffix}.json"
        json_path = os.path.join(out_dir, json_name)
        data["segments"] = segments
        data["homophone_fix"] = {
            "source": os.path.basename(path),
            "terms": len(fixer.terms),
            "fuzzy": fuzzy,
            "replacements": total_replace,
            "hits": hit_counter,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        artifacts = [f"output/{json_name}"]
        output_format = str(node_config.get("output_format", "json")).lower()
        if is_srt or output_format == "srt":
            srt_name = f"homophone_fixed{node_suffix}.srt"
            with open(os.path.join(out_dir, srt_name), "w", encoding="utf-8") as f:
                f.write(self._to_srt(segments))
            artifacts.append(f"output/{srt_name}")

        report_name = f"homophone_report{node_suffix}.txt"
        with open(os.path.join(out_dir, report_name), "w", encoding="utf-8") as f:
            f.write(f"输入: {os.path.basename(path)}\n")
            f.write(f"术语数: {len(fixer.terms)}  模糊音: {fuzzy}\n")
            f.write(f"替换次数: {total_replace}\n")
            for term, cnt in sorted(hit_counter.items(), key=lambda kv: -kv[1]):
                f.write(f"  {term} x{cnt}\n")
        artifacts.append(f"output/{report_name}")

        if callback:
            callback(100, f"同音字修复完成：替换 {total_replace} 处")

        txt = "\n".join(f"{t} x{c}" for t, c in sorted(hit_counter.items(), key=lambda kv: -kv[1]))
        return {
            "artifacts": artifacts,
            "outputs": {
                "output": f"output/{json_name}",
                "text": f"output/{report_name}",
            },
            "replacements": total_replace,
            "hits": hit_counter,
            "report": txt,
        }
