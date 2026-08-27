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
    def _first_mismatch(ref: str, sub: str):
        i = j = 0
        while j < len(sub):
            while i < len(ref) and ref[i] != sub[j]:
                i += 1
            if i >= len(ref):
                return i, j
            i += 1
            j += 1
        return i, j

    @staticmethod
    def _seg_spans(segments):
        spans = []
        pos = 0
        for idx, seg in enumerate(segments or []):
            n = S_ASRResultValidate._norm(seg.get("text") or "")
            spans.append({"seg": idx, "start": pos, "end": pos + len(n),
                          "text": seg.get("text") or "", "norm": n})
            pos += len(n)
        return spans

    @staticmethod
    def _word_spans(segments):
        spans = []
        pos = 0
        for sidx, seg in enumerate(segments or []):
            for widx, w in enumerate(seg.get("words") or []):
                n = S_ASRResultValidate._norm(w.get("word") or "")
                spans.append({"seg": sidx, "word": widx, "start": pos,
                              "end": pos + len(n), "text": w.get("word") or "", "norm": n})
                pos += len(n)
        return spans

    @staticmethod
    def _locate(spans, idx):
        for sp in spans:
            if sp["start"] <= idx < sp["end"]:
                return sp
        return spans[-1] if spans else None

    @staticmethod
    def _snippet(norm_str, idx, width=24):
        s = max(0, idx - width)
        e = min(len(norm_str), idx + width)
        return norm_str[s:e]

    # ------------------------------------------------------------------ #
    # 错误构造
    # ------------------------------------------------------------------ #
    @staticmethod
    def _raise(where, title, ref, sub, i, j, locator):
        sp = S_ASRResultValidate._locate(locator, j) if locator else None
        if sp is not None:
            seg_no = sp.get("seg", "?") + 1
            local = j - sp["start"]
            if "word" in sp:
                loc = f"segments 第 {seg_no} 段 / word 第 {sp['word'] + 1} 个（段内第 {local} 字符，归一化后）"
            else:
                loc = f"segments 第 {seg_no} 段（段内第 {local} 字符，归一化后）"
        else:
            loc = f"text 第 {j + 1} 个字符（归一化后）"
        char = sub[j] if j < len(sub) else "<文本结束>"
        exp = ref[i] if i < len(ref) else "<文本结束>"
        snip = S_ASRResultValidate._snippet(sub, j)
        raise ValueError(
            f"ASR 校验未通过（{where}）：\n"
            f"  · {title}\n"
            f"  · 偏离位置：{loc}\n"
            f"  · 期望字符：{exp!r}，实际未匹配字符：{char!r}\n"
            f"  · 上下文（去标点/空白后）：…{snip}…\n"
            f"  · 已顺序匹配：{i}/{len(ref)} 字符"
        )

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

        # 第一级：压平 segments 应为 text 的子序列（顺序匹配）。
        # 仅校验「方向」：每个 segment 字符都应在 text 中出现，
        # 否则说明 segment 文本在全文里找不到，下游时间轴锚定会失败。
        if text is not None and str(text).strip() != "":
            if callback:
                callback(30, "校验 text 与压平后的 segments ...")
            nt = self._norm(text)
            ns = self._norm(self._flatten_seg_text(segments))
            if not ns:
                raise ValueError("ASR 校验未通过：segments 文本全部为空")
            i1, j1 = self._first_mismatch(nt, ns)
            if j1 < len(ns):
                self._raise("text ↔ segments",
                            "segments 中存在 text 里找不到的内容（segment 文本无法在全文锚定）",
                            nt, ns, i1, j1, self._seg_spans(segments))
        elif callback:
            callback(40, "未提供 text，跳过 text/segments 校验，仅校验 segments/words")

        # 第二级：压平 words 应为压平 segments 的子序列（顺序匹配）。
        # 仅校验「方向」：每个 word 字符都应在对应 segment 文本中出现，
        # 否则说明 word 时间戳无法在 segment 文本中锚定（稀疏/错乱）。
        # 注意：不要求反向（segments 完全被 words 覆盖），因为词级时间戳稀疏属正常。
        nseg = self._norm(self._flatten_seg_text(segments))
        nword = self._norm(self._flatten_words(segments))
        if not nword:
            if callback:
                callback(60, "segments 下无 word 时间戳，跳过 segments/words 校验")
        else:
            if callback:
                callback(60, "校验压平后的 segments 与 words ...")
            i3, j3 = self._first_mismatch(nseg, nword)
            if j3 < len(nword):
                self._raise("segments ↔ words",
                            "words 中存在 segments 文本之外的内容（word 无法在 segment 锚定）",
                            nseg, nword, i3, j3, self._word_spans(segments))

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
