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
    def _distribute_to_segments(full_text: str, segments: list) -> list:
        """把纠错后的全文按比例分布回原 segments，保留时间轴与段落数量。"""
        lens = [len((s.get("text") or "")) for s in segments]
        total_in = sum(lens) or 1
        out = []
        idx = 0
        n = len(segments)
        for i, s in enumerate(segments):
            if i == n - 1:
                part = full_text[idx:]
            else:
                take = max(0, round(len(full_text) * lens[i] / total_in))
                part = full_text[idx:idx + take]
                idx += take
            ns = copy.deepcopy(s) if isinstance(s, dict) else dict(s)
            ns["text"] = part
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
            out_asr["text"] = new_text
            segs = asr.get("segments")
            if isinstance(segs, list) and segs:
                out_asr["segments"] = self._distribute_to_segments(new_text, segs)
                # 用词级时间戳重算每段起止时间（稀疏亦可，失败保留原时间）
                words = []
                for seg in segs:
                    for w in seg.get("words", []) or []:
                        if w.get("start") is not None and w.get("end") is not None:
                            words.append(w)
                if words:
                    try:
                        from backend.utils.time_align import SentenceTimeAligner
                        aligner = SentenceTimeAligner(
                            text, words, segments=segs)
                        for seg in out_asr.get("segments", []) or []:
                            _, st, en = aligner.align_next(seg.get("text", ""))
                            if st is not None:
                                seg["start"] = st
                            if en is not None:
                                seg["end"] = en
                    except Exception as e:  # 对齐异常不影响纠错结果，保留原时间
                        print(f"[AiSubtitleCorrect] 词级时间重算失败，保留原时间：{e}")
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
