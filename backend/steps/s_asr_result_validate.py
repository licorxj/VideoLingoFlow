"""ASR 结果校验节点。

功能：
1. 读取上游传入的 ASR JSON（whisper / 任意 ASR 引擎输出）。
2. 两级一致性校验（均先「去标点、去空白、转小写」再顺序匹配）：
   - 第一级：text 与「压平后的 segments」顺序一致；
   - 第二级：压平后的 segments 与「压平后的 words」顺序一致。
3. 校验通过：原样透传输出 ASR JSON（文件名带节点 id 后缀）；
   校验不通过：抛出 ValueError，并在错误信息中指明偏离位置与上下文。
"""
import os
import re
import json
import glob

from backend.steps.base_step import BaseStep


class S_ASRResultValidate(BaseStep):
    step_id = "asr_result_validate"

    # ------------------------------------------------------------------ #
    # 归一化与压平
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norm(s) -> str:
        s = (s or "").lower()
        s = re.sub(r"[^\w\s]", "", s)   # 去标点（保留字母/数字/下划线/空白）
        s = re.sub(r"\s+", "", s)       # 去空白
        return s

    @staticmethod
    def _flatten_seg_text(segments) -> str:
        return "".join((seg.get("text") or "") for seg in (segments or []))

    @staticmethod
    def _flatten_words(segments) -> str:
        out = []
        for seg in (segments or []):
            for w in (seg.get("words") or []):
                out.append(w.get("word") or "")
        return "".join(out)

    # ------------------------------------------------------------------ #
    # 顺序匹配：返回 (i, j)，为 (len(ref), len(sub)) 表示 sub 是 ref 的子序列
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_diff(a: str, b: str):
        """返回两串首个不同字符的下标；完全相同返回 -1；长度不同返回较短串长度。"""
        n = min(len(a), len(b))
        for k in range(n):
            if a[k] != b[k]:
                return k
        if len(a) != len(b):
            return n
        return -1

    @staticmethod
    def _snippet(norm_str, idx, width=24):
        s = max(0, idx - width)
        e = min(len(norm_str), idx + width)
        return norm_str[s:e]

    # ------------------------------------------------------------------ #
    # 主校验
    # ------------------------------------------------------------------ #
    def _validate(self, asr, callback):
        if not isinstance(asr, dict):
            raise ValueError("ASR 校验未通过：输入不是合法的 JSON 对象（dict）")

        segments = asr.get("segments")
        text = asr.get("text")
        if not isinstance(segments, list) or not segments:
            raise ValueError("ASR 校验未通过：缺少 segments 或 segments 为空")

        # 第一级：全文 text 必须与「压平后的 segments」完全一致（归一化后）。
        # 之前只校验「segments 是 text 的子序列（方向）」，会漏掉 text 比 segments 多/少内容，
        # 故改为全文相等校验。
        if text is not None and str(text).strip() != "":
            if callback:
                callback(30, "校验 text 与压平后的 segments ...")
            nt = self._norm(text)
            ns = self._norm(self._flatten_seg_text(segments))
            if not ns:
                raise ValueError("ASR 校验未通过：segments 文本全部为空")
            if nt != ns:
                k = self._first_diff(nt, ns)
                raise ValueError(
                    f"ASR 校验未通过（text ↔ segments）：\n"
                    f"  · 全文 text 与压平后的 segments 不完全一致（去标点/空白/大小写后）。\n"
                    f"  · 全文 text 长度 {len(nt)}，segments 压平长度 {len(ns)}。\n"
                    f"  · text(归一化):    …{self._snippet(nt, k if k >= 0 else 0)}…\n"
                    f"  · segments(归一化): …{self._snippet(ns, k if k >= 0 else 0)}…"
                )
        elif callback:
            callback(40, "未提供 text，跳过 text/segments 校验，仅校验 segments/words")

        # 第二级：逐段校验 words 与「该段 text」完全一致（归一化后）。
        # 关键修复：之前把【所有段】的 words 拼成一串、所有段 text 拼成一串后只做
        # 「全局子序列（方向）」匹配，导致某段的垃圾词可借用其它段文本蒙混过关，
        # 空 words 的段被直接跳过，且从不要求 words 覆盖 segment 文本。
        # 现改为逐段「完全相等」校验：每段 text 必须完整、且只由其 words 构成。
        if callback:
            callback(60, "逐段校验 segments 文本与 words ...")
        for sidx, seg in enumerate(segments):
            seg_norm = self._norm(seg.get("text") or "")
            word_norm = self._norm(self._flatten_words([seg]))
            if seg_norm != word_norm:
                k = self._first_diff(seg_norm, word_norm)
                raise ValueError(
                    f"ASR 校验未通过（segments ↔ words）：\n"
                    f"  · segments 第 {sidx + 1} 段的文本与 words 不完全一致"
                    f"（去标点/空白/大小写后）。\n"
                    f"  · segment 文本长度 {len(seg_norm)}，words 压平长度 {len(word_norm)}。\n"
                    f"  · segment 文本(归一化): …{self._snippet(seg_norm, k if k >= 0 else 0)}…\n"
                    f"  · words 压平(归一化):   …{self._snippet(word_norm, k if k >= 0 else 0)}…\n"
                    f"  · 该段原文: {seg.get('text')!r}\n"
                    f"  · 该段 words: {[w.get('word') for w in (seg.get('words') or [])]!r}"
                )

    # ------------------------------------------------------------------ #
    # 输入读取 / 运行
    # ------------------------------------------------------------------ #
    def _load_asr(self, task_dir):
        raw = (getattr(self, "_step_inputs", {}) or {}).get("json")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        path = raw if isinstance(raw, str) else None
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), path
        # 兜底：在 cache 中查找 asr_result*.json
        matches = sorted(glob.glob(os.path.join(task_dir, "cache", "asr_result*.json")),
                         key=os.path.getmtime, reverse=True)
        for m in matches:
            try:
                with open(m, "r", encoding="utf-8") as f:
                    return json.load(f), m
            except Exception:
                continue
        raise ValueError(
            "ASR 校验未通过：无法读取 ASR JSON 输入"
            "（step_inputs['json'] 为空且 cache 中无 asr_result*.json）"
        )

    def check_artifact(self, task_dir):
        node_id = getattr(self, "_node_id", "")
        name = f"asr_result_{node_id}.json" if node_id else "asr_result.json"
        return os.path.isfile(os.path.join(task_dir, "cache", name))

    def validate_inputs(self, task_dir):
        raw = (getattr(self, "_step_inputs", {}) or {}).get("json")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        path = raw if isinstance(raw, str) else None
        if path and os.path.isfile(path):
            return True
        # 兜底：cache 中存在 asr_result*.json
        if find_artifact(os.path.join(task_dir, "cache"), "asr_result"):
            return True
        return False

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        asr_data, src = self._load_asr(task_dir)
        if callback:
            callback(10, f"读取 ASR JSON：{os.path.basename(src)}")
        self._validate(asr_data, callback)

        out_name = f"asr_result_{node_id}.json" if node_id else "asr_result.json"
        out_path = os.path.join(cache_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(asr_data, f, ensure_ascii=False, indent=2)

        self.artifacts = [os.path.join("cache", out_name)]
        if callback:
            callback(100, "ASR 结果校验通过，已透传输出")
        return {
            "artifacts": self.artifacts,
            "outputs": {"json": os.path.join("cache", out_name)},
            "valid": True,
        }
