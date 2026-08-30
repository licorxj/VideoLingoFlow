"""ASR 结果校验节点。

功能：
1. 读取「连线接入」的输入 ASR JSON 文件路径（step_inputs['json']），不做任何
   文件名兜底匹配。
2. 两级一致性校验（均先「去标点、去空白、转小写」再顺序匹配）：
   - 第一级：text 与「压平后的 segments」完全一致；
   - 第二级：逐段校验 segment 文本与 words 完全一致。
3. 校验通过：直接把「输入文件路径」作为本节点输出（不新建文件、不改写内容）；
   校验不通过：抛出 ValueError，并在错误信息中指明偏离位置与上下文。
"""
import os
import re
import json

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
        """按输入类型分派校验：dict 视为 ASR 对象，list 视为句子列表。"""
        if isinstance(asr, dict):
            self._validate_asr_object(asr, callback)
        elif isinstance(asr, list):
            self._validate_sentence_list(asr, callback)
        else:
            raise ValueError(
                "ASR 校验未通过：输入类型无法识别"
                f"（期望 ASR 对象 dict 或句子列表 list，实际为 {type(asr).__name__}）"
            )

    def _validate_asr_object(self, asr, callback):
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

    def _validate_sentence_list(self, sentences, callback):
        """兼容「句子分割」产出的句子列表：[{id, text, words:[...], ...}, ...]。

        校验：
          - 列表非空；
          - 每项为 dict；
          - 每句的 text 非空；
          - 若带 words，句子 text 必须（归一化后）完整、且仅由其 words 构成
            （与 ASR 对象的「segment ↔ words」同级一致性）。
        """
        if not sentences:
            raise ValueError("ASR 校验未通过（句子列表）：句子列表为空")

        if callback:
            callback(30, f"校验句子列表（共 {len(sentences)} 句）...")

        for idx, s in enumerate(sentences):
            sid = (s.get("id", idx + 1) if isinstance(s, dict) else idx + 1)
            if not isinstance(s, dict):
                raise ValueError(
                    f"ASR 校验未通过（句子列表）：第 {idx + 1} 项不是对象（dict），"
                    f"而是 {type(s).__name__}"
                )
            text = s.get("text")
            if text is None or str(text).strip() == "":
                raise ValueError(
                    f"ASR 校验未通过（句子列表）：第 {idx + 1} 句（id={sid}）的 text 为空"
                )

            words = s.get("words") or []
            if words:
                seg_norm = self._norm(text)
                word_norm = self._norm(self._flatten_words([s]))
                if seg_norm != word_norm:
                    # 定位首个差异字符下标（两副本通用，不依赖特定辅助方法）
                    n = min(len(seg_norm), len(word_norm))
                    k = -1
                    for _i in range(n):
                        if seg_norm[_i] != word_norm[_i]:
                            k = _i
                            break
                    if k == -1 and len(seg_norm) != len(word_norm):
                        k = n
                    raise ValueError(
                        f"ASR 校验未通过（句子列表）：第 {idx + 1} 句（id={sid}）"
                        f"的文本与 words 不完全一致"
                        f"（去标点/空白/大小写后）。\n"
                        f"  · 句子文本长度 {len(seg_norm)}，words 压平长度 {len(word_norm)}。\n"
                        f"  · 句子文本(归一化): …{self._snippet(seg_norm, k if k >= 0 else 0)}…\n"
                        f"  · words 压平(归一化): …{self._snippet(word_norm, k if k >= 0 else 0)}…\n"
                        f"  · 该句原文: {text!r}\n"
                        f"  · 该句 words: {[w.get('word') for w in words]!r}"
                    )

        if callback:
            callback(60, "句子列表校验通过")

    # ------------------------------------------------------------------ #
    # 输入读取 / 运行
    # ------------------------------------------------------------------ #
    def _input_path(self):
        """忠实取回连线接入的输入文件路径（step_inputs['json']）。"""
        raw = (getattr(self, "_step_inputs", {}) or {}).get("json")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return raw if isinstance(raw, str) else None

    def _resolve_input_path(self, task_dir):
        """将输入路径解析为绝对路径：相对路径以 task_dir 为基准，与引擎其它节点一致。"""
        path = self._input_path()
        if not path:
            return None
        return path if os.path.isabs(path) else os.path.join(task_dir, path)

    def _load_asr(self, task_dir):
        path = self._input_path()
        if not path:
            raise ValueError(
                "ASR 校验未通过：未接入有效的 ASR JSON 输入文件（step_inputs['json'] 为空）"
            )
        abs_path = self._resolve_input_path(task_dir)
        if not os.path.isfile(abs_path):
            raise ValueError(
                "ASR 校验未通过：未接入有效的 ASR JSON 输入文件"
                f"（step_inputs['json'] 指向的文件不存在：{abs_path}）"
            )
        with open(abs_path, "r", encoding="utf-8") as f:
            return json.load(f), path

    def check_artifact(self, task_dir):
        # 本节点不生成新文件，产物即「接入的输入文件」本身，存在即可复跑/跳过。
        path = self._resolve_input_path(task_dir)
        return bool(path) and os.path.isfile(path)

    def validate_inputs(self, task_dir):
        path = self._resolve_input_path(task_dir)
        return bool(path) and os.path.isfile(path)

    def run(self, task_dir, callback=None, cancel_callback=None):
        src = self._input_path()
        asr_data, src = self._load_asr(task_dir)
        if callback:
            callback(10, f"读取 ASR JSON：{os.path.basename(src)}")
        self._validate(asr_data, callback)

        # 校验通过：直接把输入文件路径作为输出，不新建文件、不改写内容。
        self.artifacts = [src]
        if callback:
            callback(100, "ASR 结果校验通过，已透传输入文件")
        return {
            "artifacts": self.artifacts,
            "outputs": {"json": src},
            "valid": True,
        }
