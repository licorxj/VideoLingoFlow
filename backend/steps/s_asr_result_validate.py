"""ASR 结果校验节点。

功能：
1. 读取「连线接入」的输入 ASR JSON 文件路径（step_inputs['json']），不做任何
   文件名兜底匹配。
2. 两级一致性校验（均先「去标点、去空白、转小写」再顺序匹配）：
   - 第一级：text 与「压平后的 segments」完全一致；
   - 第二级：逐段校验 segment 文本与 words 完全一致。
3. 校验通过：直接把「输入文件路径」作为本节点输出（不新建文件、不改写内容）；
   校验不通过：抛出 ValueError，并在错误信息中指明偏离位置与上下文。
4. 可选「自动修复」（节点配置 auto_fix 勾选后启用）：检测到不一致时自动修复并写回输入文件：
   - text ↔ segments 不一致：以 segments 原文重拼 text（保留标点）；
   - segments ↔ words 不一致：以 words 重拼该段 text，并用首个 word 的 start 更新该段起始时间；
   - speaker 补齐：段无 speaker 取首个 word 的，word 无 speaker 取所属段的，两者都无则填 "S01"。
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

    def _align_words_to_text(self, text, words):
        """Re-derive a ``words`` list whose (normalized) concatenation equals the
        normalized ``text``, by consuming the original words in order and splitting
        any boundary-straddling word proportionally by character count.

        Handles the recoverable inconsistency where a sentence's ``text`` is a *prefix*
        of its ``words`` (the text was truncated at a word boundary while the whole
        word was kept): overflow beyond ``text`` is dropped, and the boundary word is
        split (text + proportional timestamp) so the result exactly matches ``text``.

        Returns the repaired words list, or ``None`` when the mismatch is not of this
        recoverable form (e.g. ``text`` contains characters absent from ``words``).
        """
        tn = self._norm(text)
        if not tn or not words:
            return None
        result = []
        wi, wp, covered = 0, 0, 0
        n = len(words)
        while covered < len(tn) and wi < n:
            w = words[wi]
            wt = self._norm(w.get("word", ""))
            if not wt:
                wi += 1
                wp = 0
                continue
            remaining = len(wt) - wp
            take = min(remaining, len(tn) - covered)
            if take <= 0:
                break
            sub_text = wt[wp:wp + take]
            try:
                ws = float(w.get("start", 0) or 0)
                we = float(w.get("end", 0) or 0)
            except (TypeError, ValueError):
                ws = we = 0.0
            span = we - ws
            if span > 0:
                sub_start = ws + span * (wp / len(wt))
                sub_end = ws + span * ((wp + take) / len(wt))
            else:
                sub_start = sub_end = ws
            sub = dict(w)
            sub["word"] = sub_text
            sub["start"] = round(sub_start, 4)
            sub["end"] = round(sub_end, 4)
            result.append(sub)
            covered += take
            wp += take
            if wp >= len(wt):
                wi += 1
                wp = 0
        if self._norm("".join(r.get("word", "") for r in result)) == tn:
            return result
        return None

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

    # ------------------------------------------------------------------ #
    # 自动修复（仅在节点开启「自动修复」时启用）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _has_speaker(value) -> bool:
        """speaker 是否为有效值（排除 None / 空串 / 字符串形式的 null、none）。"""
        if value in (None, ""):
            return False
        return str(value).strip().lower() not in ("null", "none", "nan")

    @staticmethod
    def _read_auto_fix(config) -> bool:
        value = (config or {}).get("auto_fix")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return False

    def _fix_segments_from_words(self, items) -> int:
        """规则一：以 words 为准重建每段 text，并更新该段的起始时间。

        以「下属 words 拼接到 segments」为准；words 缺失的段跳过（无从对齐）。
        起始时间取首个 word 的 start；若该段 end 缺失或早于新 start，
        则用末个 word 的 end 兜底，避免出现 end < start 的坏区间。
        """
        changed = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            words = item.get("words") or []
            if not words:
                continue
            rebuilt = "".join(str(w.get("word") or "") for w in words)
            # 以「归一化后是否一致」判定是否真的对不上：words 通常不含标点，
            # 若 segment 原文仅多出标点则应视为一致、不覆盖，优先保留原有标点
            # （与校验口径统一，避免把「，」「。」等标点抹掉）。
            if self._norm(rebuilt) != self._norm(item.get("text") or ""):
                item["text"] = rebuilt
                changed += 1
            starts = [w.get("start") for w in words if isinstance(w.get("start"), (int, float))]
            new_start = round(float(starts[0]), 4) if starts else None
            if new_start is not None and item.get("start") != new_start:
                item["start"] = new_start
                changed += 1
            ends = [w.get("end") for w in words if isinstance(w.get("end"), (int, float))]
            cur_end = item.get("end")
            if ends and (not isinstance(cur_end, (int, float))
                         or cur_end < float(new_start if new_start is not None else 0)):
                item["end"] = round(float(ends[-1]), 4)
                changed += 1
        return changed

    def _fix_speakers(self, items) -> int:
        """规则三：补齐 speaker 标签。

        segment 无 speaker → 取该段首个 word 的 speaker；
        word 无 speaker → 取所属 segment 的 speaker；
        两者都无 → 填 "S01"。
        """
        changed = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            words = item.get("words") or []
            speaker = item.get("speaker")
            if not self._has_speaker(speaker):
                speaker = ""
                for w in words:
                    if isinstance(w, dict) and self._has_speaker(w.get("speaker")):
                        speaker = w.get("speaker")
                        break
            if not self._has_speaker(speaker):
                speaker = "S01"
            if item.get("speaker") != speaker:
                item["speaker"] = speaker
                changed += 1
            for w in words:
                if isinstance(w, dict) and not self._has_speaker(w.get("speaker")):
                    w["speaker"] = speaker
                    changed += 1
        return changed

    def _fix_text_from_segments(self, asr, segments) -> int:
        """规则二：以 segments 原文重拼全文 text（保留各段自带标点）。"""
        rebuilt = "".join(str(seg.get("text") or "") for seg in segments)
        if asr.get("text") != rebuilt:
            asr["text"] = rebuilt
            return 1
        return 0

    def _apply_auto_fix(self, asr, segments, callback=None) -> int:
        """按「words 为准 → text 跟随 segments → speaker 补齐」顺序统一数据。

        先修正 segments（规则一），再由 segments 重拼 text（规则二），
        从而保证修复后 text / segments / words 三者一致；最后补齐 speaker（规则三）。
        """
        fixed_seg = self._fix_segments_from_words(segments)
        fixed_text = self._fix_text_from_segments(asr, segments) if isinstance(asr, dict) else 0
        fixed_speaker = self._fix_speakers(segments)
        total = fixed_seg + fixed_text + fixed_speaker
        if total > 0:
            self._repaired = True
        if callback:
            callback(50, f"自动修复：段文本/时间 {fixed_seg} 处、全文 text {fixed_text} 处、speaker {fixed_speaker} 处")
        return total

    def _validate_asr_object(self, asr, callback):
        if not isinstance(asr, dict):
            raise ValueError("ASR 校验未通过：输入不是合法的 JSON 对象（dict）")

        segments = asr.get("segments")
        text = asr.get("text")
        if not isinstance(segments, list) or not segments:
            raise ValueError("ASR 校验未通过：缺少 segments 或 segments 为空")

        # 自动修复：先统一 segments / words / text / speaker，再走下面的校验做复核
        if self._auto_fix_enabled:
            self._apply_auto_fix(asr, segments, callback)

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
            if self._auto_fix_enabled and not (seg.get("words") or []):
                # 自动修复模式：该段无 words 可对齐，保留其文本、不阻断流程
                continue
            seg_norm = self._norm(seg.get("text") or "")
            word_norm = self._norm(self._flatten_words([seg]))
            if seg_norm != word_norm:
                # Recoverable: text is a prefix of words -> re-derive words to match text.
                repaired = self._align_words_to_text(
                    seg.get("text") or "", seg.get("words") or []
                )
                if repaired is not None:
                    seg["words"] = repaired
                    self._repaired = True
                    continue
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

        # 自动修复：句子列表复用同一套规则（以 words 重建文本与起始时间 + 补齐 speaker）
        if self._auto_fix_enabled:
            fixed_seg = self._fix_segments_from_words(sentences)
            fixed_speaker = self._fix_speakers(sentences)
            if fixed_seg or fixed_speaker:
                self._repaired = True
                if callback:
                    callback(40, f"自动修复：句子文本/时间 {fixed_seg} 处、speaker {fixed_speaker} 处")

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
                    # Recoverable: text is a prefix of words -> re-derive words to match text.
                    repaired = self._align_words_to_text(text, words)
                    if repaired is not None:
                        s["words"] = repaired
                        self._repaired = True
                    else:
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
        self._repaired = False
        self._auto_fix_enabled = self._read_auto_fix(getattr(self, "_node_config", {}) or {})
        if callback:
            callback(10, f"读取 ASR JSON：{os.path.basename(src)}"
                     + ("（自动修复已开启）" if self._auto_fix_enabled else ""))
        self._validate(asr_data, callback)

        # 若自动修复了 text/words 不一致，将修复结果写回输入文件，使下游拿到一致数据。
        if self._repaired:
            abs_path = self._resolve_input_path(task_dir)
            try:
                with open(abs_path, "w", encoding="utf-8") as f:
                    json.dump(asr_data, f, ensure_ascii=False, indent=2)
                if callback:
                    callback(95, "已自动修复不一致并写回输入文件")
            except Exception as e:
                print(f"[ASR 校验] 写回修复结果失败：{e}")

        # 校验通过：直接把输入文件路径作为输出，不新建文件、不改写内容。
        self.artifacts = [src]
        if callback:
            callback(100, "ASR 结果校验通过，已透传输入文件")
        return {
            "artifacts": self.artifacts,
            "outputs": {"json": src},
            "valid": True,
        }
