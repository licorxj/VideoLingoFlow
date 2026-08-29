"""s_ai_subtitle_correct: AI 字幕纠错。

读取 ASR 结果 JSON，提取全文（优先 text 键；缺失则压平 segments），按字数上限
优先在 标点 > 空格 边界切分为批次，携带「专有名词」等上下文请求 LLM 修复 ASR 识别
错误、去除多余空格并修正标点。Prompt 通过项目的 LLM 组装层（prompt_templates.json
中 id=ai_subtitle_correct 的模板）渲染，用户可在「Prompt 工程」中自行修改。
"""
import copy
import json
import os
import re
import unicodedata
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.llm.llm_client import get_llm_client


_PUNCTS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "config", "language_puncts.json")
)

_SYSTEM_PROMPT = (
    "你是一个专业的 ASR（语音识别）结果纠错助手。任务：对给定的识别文本进行纠错，"
    "使其准确、通顺、标点规范。严格要求："
    "1) 修正识别错误（同音字、形近字、专有名词、语法等），在保持原意的前提下修正；"
    "2) 去除多余空格（中文词间不应有空格；英文保留单词间空格，去除异常/多余空格）；"
    "3) 修正并补全标点符号，使语句自然通顺；"
    "4) 不得增删原意，不得添加任何解释、标题、Markdown 或额外内容；"
    "5) 只输出纠错后的目标文本本身。"
)

_FALLBACK_USER = (
    "以下是 ASR（语音识别）结果文本，可能存在识别错误、多余空格和标点问题。请纠错：\n"
    "1. 修正识别错误（同音字、形近字、专有名词、语法等），保持原意不变；\n"
    "2. 去除多余空格（中文词间不应有空格；英文保留单词间空格，去除异常空格）；\n"
    "3. 修正并补全标点符号，使语句通顺自然；\n"
    "4. 不得增删原意，不得添加任何解释、标题或 Markdown。\n"
    "{proper_nouns_block}"
    "【待纠错文本】\n"
    "{core}"
)


class S_AiSubtitleCorrect(BaseStep):
    step_id = "ai_subtitle_correct"
    step_name = "AI字幕纠错"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ---------- 工具 ----------
    @staticmethod
    def _is_text_char(ch: str) -> bool:
        if ch.isspace():
            return False
        if unicodedata.category(ch).startswith("P"):
            return False
        return True

    @staticmethod
    def _load_puncts(lang: str) -> set:
        try:
            with open(_PUNCTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return set()
        common = set(data.get("_common", {}).get("sentence_ends", [])) | set(
            data.get("_common", {}).get("clause_breaks", [])
        )
        key = (lang or "").split("-")[0].lower()
        if not key or key == "auto":
            key = "_default"
        lang_data = data.get(key, {})
        return common | set(lang_data.get("sentence_ends", [])) | set(
            lang_data.get("clause_breaks", [])
        )

    @staticmethod
    def _resolve_input_file(raw, task_dir: str):
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

    @staticmethod
    def _split_chunks(text: str, max_chars: int, puncts: set) -> list:
        chunks = []
        start = 0
        n = len(text)
        while start < n:
            end = min(start + max_chars, n)
            if end >= n:
                chunks.append(text[start:n])
                break
            cut = S_AiSubtitleCorrect._find_boundary(text, start, end, puncts)
            if cut is None or cut <= start:
                cut = end  # 硬切
            chunks.append(text[start:cut])
            start = cut
            if start >= n:
                break
        return chunks

    @staticmethod
    def _find_boundary(text: str, start: int, end: int, puncts: set):
        # 切割优先级：标点 > 空格（用户要求），硬切兜底
        best_punct = None
        best_space = None
        for i in range(end - 1, start - 1, -1):
            ch = text[i]
            if ch in puncts:
                if best_punct is None:
                    best_punct = i + 1
            elif ch.isspace():
                if best_space is None:
                    best_space = i + 1
        if best_punct is not None:
            return best_punct
        if best_space is not None:
            return best_space
        return None

    @staticmethod
    def _extract_asr_text(asr) -> str:
        """读取 text；缺失则把 segments 下的句子压平为 text。"""
        if isinstance(asr, dict):
            text = asr.get("text")
            if isinstance(text, str) and text.strip():
                return text
            segs = asr.get("segments") or []
            if isinstance(segs, list):
                return "\n".join((s.get("text") or "") for s in segs if isinstance(s, dict))
        return ""

    @staticmethod
    def _rebuild_segments(new_text: str, original_segments: list) -> list:
        """把原始 segments 中（时间戳正确的）words 重新对齐到纠错后的 new_text，
        重写每段 text 为 new_text 中对应这些词的字符片段；words / speaker / 时间保持自洽。

        这是修复 text↔words 错配的根治手段：旧实现 _distribute_to_segments 按字符比例硬切
        new_text 回填，会把已纠错文本切成 ". Aar"/"on. Ha" 等不连续碎片，却保留原始词级时间
        戳，导致 text↔words 错配并向断句预处理节点传递破坏性结构。这里改为基于字符子序列把
        每个词锚定到 new_text，再按段聚合字符区间得到一致的新 text，并丢弃无法对齐的幻觉词
        （如被纠错删除的 "check"）。
        """
        from backend.utils.time_align import SentenceTimeAligner

        # 扁平化所有词并记录其所属段（仅纳入有 word 文本的 token）
        flat = []  # (seg_index, word_dict)
        for si, seg in enumerate(original_segments):
            if not isinstance(seg, dict):
                continue
            for w in seg.get("words", []) or []:
                if isinstance(w, dict) and w.get("word") is not None:
                    flat.append((si, w))
        if not flat:
            return [copy.deepcopy(s) if isinstance(s, dict) else dict(s)
                    for s in original_segments]

        try:
            aligner = SentenceTimeAligner(new_text, [w for _, w in flat])
        except Exception:
            aligner = None

        # 按顺序把每个词锚定到 new_text，记录可对齐词的对象 id 与字符区间
        spans = [None] * len(flat)
        anchored_ids = set()
        if aligner is not None:
            cursor = 0
            for i, (_, w) in enumerate(flat):
                cs, ce = aligner.span_for_text(str(w.get("word", "")), cursor)
                if cs is None:
                    spans[i] = None
                else:
                    spans[i] = (cs, ce)
                    cursor = ce
                    anchored_ids.add(id(w))

        out = []
        for si, seg in enumerate(original_segments):
            ns = copy.deepcopy(seg) if isinstance(seg, dict) else dict(seg)
            # 仅保留能对齐到纠错文本的词（去除幻觉词），保持 words 与 text 一致
            seg_words = [w for w in (seg.get("words", []) or [])
                         if isinstance(w, dict) and id(w) in anchored_ids]
            ns["words"] = seg_words
            seg_spans = [sp for (sj, _), sp in zip(flat, spans)
                         if sj == si and sp is not None]
            if seg_spans:
                lo = min(cs for cs, _ in seg_spans)
                hi = max(ce for _, ce in seg_spans)
                ns["text"] = new_text[lo:hi]
                if seg_words:
                    ns["start"] = min(w.get("start", ns.get("start")) or ns.get("start", 0)
                                      for w in seg_words)
                    ns["end"] = max(w.get("end", ns.get("end")) or ns.get("end", 0)
                                    for w in seg_words)
            else:
                # 该段词全部无法对齐到纠错文本（如整段被纠错删除），保留原 text 兜底
                ns["text"] = seg.get("text", "") if isinstance(seg, dict) else ""
            out.append(ns)
        return out

    # ---------- 主流程 ----------
    def run(self, task_dir: str, callback: Optional[Callable] = None, cancel_callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        raw = step_inputs.get("json") or step_inputs.get("any") or step_inputs.get("file")
        path = self._resolve_input_file(raw, task_dir)
        if not path:
            raise ValueError("未收到有效的 ASR JSON 文件输入")

        with open(path, "r", encoding="utf-8") as f:
            asr = json.load(f)

        text = self._extract_asr_text(asr)
        if not text:
            raise ValueError("ASR JSON 中未找到 text 或有效 segments 全文")

        # 语言（仅用于切割标点集合；纠错本身由 LLM 完成）
        lang = (asr.get("language") or "zh" if isinstance(asr, dict) else "zh")
        lang = (lang or "zh").strip().lower() or "zh"
        puncts = self._load_puncts(lang)

        max_chars = 2000
        try:
            max_chars = int(node_config.get("maxChars", 2000) or 2000)
        except (TypeError, ValueError):
            pass
        max_chars = max(200, max_chars)

        # 专有名词（逗号分隔多个）
        proper_nouns = (node_config.get("properNouns") or "").strip()

        chunks = self._split_chunks(text, max_chars, puncts)
        if callback:
            callback(10, f"分批次：{len(chunks)} 段，上限={max_chars}字")

        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        llm = get_llm_client()

        repaired_parts = []
        total = len(chunks)
        for idx, core in enumerate(chunks):
            if cancel_callback and cancel_callback():
                break

            assembled = svc.assemble_prompt("ai_subtitle_correct", {
                "core": core,
                "proper_nouns": proper_nouns,
            })
            if assembled.get("found") and (assembled.get("system_prompt") or assembled.get("user_prompt")):
                system_prompt = assembled.get("system_prompt") or _SYSTEM_PROMPT
                user = assembled.get("user_prompt") or ""
            else:
                block = ""
                if proper_nouns:
                    block = f"以下为需要特别正确识别的专有名词（逗号分隔），请优先采用这些写法：{proper_nouns}\n"
                user = _FALLBACK_USER.format(proper_nouns_block=block, core=core)
                system_prompt = _SYSTEM_PROMPT

            try:
                result = llm.chat(
                    step_name="vlf-02",
                    prompt=user,
                    response_json=False,
                    stream=False,
                    log=True,
                    system_prompt=system_prompt,
                )
            except Exception as e:
                raise RuntimeError(f"LLM 字幕纠错请求失败：{e}") from e

            repaired = result if isinstance(result, str) else str(result)
            repaired_parts.append(repaired.strip())

            if callback:
                callback(int(10 + (idx + 1) / total * 85), f"字幕纠错 {idx + 1}/{total}")

        new_text = "".join(repaired_parts)

        # 组装输出 JSON：保留原结构，回填纠错后的 text / segments
        if isinstance(asr, dict):
            out_asr = copy.deepcopy(asr)
            # 方案A：以纠错后的 new_text 为唯一规范全文。不再把 new_text 按比例硬切回原
            # segments（旧逻辑会制造 text↔words 错配），而是把原始（时间戳正确的）words 重新
            # 对齐到 new_text 并重建自洽的 segments，交给下游断句预处理节点基于纠正后的全文
            # 统一重新断句并正确对齐词级时间轴。
            out_asr["text"] = new_text
            segs = asr.get("segments")
            if isinstance(segs, list) and segs:
                out_asr["segments"] = self._rebuild_segments(new_text, segs)
        else:
            out_asr = {"text": new_text}

        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        node_id = getattr(self, "_node_id", "unknown")
        out_name = f"asr_corrected_{node_id}.json"
        out_path = os.path.join(out_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_asr, f, ensure_ascii=False, indent=2)

        txt_name = f"asr_corrected_{node_id}.txt"
        txt_path = os.path.join(out_dir, txt_name)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(new_text)

        if callback:
            callback(100, f"字幕纠错完成 -> {out_name} / {txt_name}")

        return {
            "artifacts": [f"output/{out_name}", f"output/{txt_name}"],
            "outputs": {
                "output": f"output/{out_name}",
                "text": f"output/{txt_name}",
            },
        }


StepAiSubtitleCorrect = S_AiSubtitleCorrect
