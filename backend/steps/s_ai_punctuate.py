"""s_ai_punctuate: AI 标点补全。

读取 ASR 结果 JSON，提取全文（优先 text 键；缺失则压平 segments），按字数上限
优先在 换行 > 标点(语言专属) > 空格 > 硬切 边界切分为批次，分批携带前后 30 字符
上下文请求 LLM 修复标点，并按文字字符对齐精确提取核心段落，避免上下文重叠污染。
"""
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
    "你是一个专业的文本标点修复助手。任务：为给定文本补全与修正标点符号，"
    "使其符合规范的中文（或对应语言）标点习惯。严格要求："
    "1) 绝对不要增删、替换或改写任何文字字符（汉字、字母、数字、单词等）；"
    "2) 只能在文字之间或末尾添加标点，或修正已有错误标点；"
    "3) 不要输出任何解释、Markdown 代码块或额外内容，直接输出修复标点后的纯文本。"
)


class S_AiPunctuate(BaseStep):
    step_id = "ai_punctuate"
    step_name = "AI标点补全"
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
    def _resolve_input_language(task_dir: str) -> str:
        wf_path = os.path.join(task_dir, "workflow.json")
        if not os.path.exists(wf_path):
            return "auto"
        try:
            with open(wf_path, "r", encoding="utf-8") as f:
                wf = json.load(f)
        except Exception:
            return "auto"
        for node in wf.get("nodes", []):
            if node.get("data", {}).get("nodeType") == "input":
                src = node.get("data", {}).get("config", {}).get("source_language", "auto")
                return src or "auto"
        return "auto"

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
            cut = S_AiPunctuate._find_boundary(text, start, end, puncts)
            if cut is None or cut <= start:
                cut = end  # 硬切
            chunks.append(text[start:cut])
            start = cut
            if start >= n:
                break
        return chunks

    @staticmethod
    def _find_boundary(text: str, start: int, end: int, puncts: set):
        best_newline = None
        best_punct = None
        best_space = None
        for i in range(end - 1, start - 1, -1):
            ch = text[i]
            if ch == "\n":
                best_newline = i + 1
                break
            if ch in puncts:
                if best_punct is None:
                    best_punct = i + 1
            elif ch.isspace():
                if best_space is None:
                    best_space = i + 1
        if best_newline is not None:
            return best_newline
        if best_punct is not None:
            return best_punct
        if best_space is not None:
            return best_space
        return None

    @staticmethod
    def _extract_core(repaired: str, prefix: str, core: str) -> str:
        """从 LLM 结果中提取 core 段落：优先按包裹标记，回退按文字字符对齐。"""
        m = re.search(r"###CORE_START###(.*?)###CORE_END###", repaired, re.DOTALL)
        if m:
            return m.group(1).strip("\n")
        # 回退：按文字字符对齐提取（丢弃前后上下文）
        p_cnt = sum(1 for c in prefix if S_AiPunctuate._is_text_char(c))
        c_cnt = sum(1 for c in core if S_AiPunctuate._is_text_char(c))
        collected = []
        cnt = 0
        for ch in repaired:
            is_text = S_AiPunctuate._is_text_char(ch)
            if p_cnt <= cnt < p_cnt + c_cnt:
                collected.append(ch)
            if is_text:
                cnt += 1
        return "".join(collected)

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
        if not isinstance(asr, dict):
            raise ValueError("ASR JSON 顶层应为对象")

        # 提取全文：优先 text 键，缺失则压平 segments
        text = asr.get("text")
        if not isinstance(text, str) or not text.strip():
            segs = asr.get("segments") or []
            text = " ".join((s.get("text") or "").strip() for s in segs).strip()
        if not text:
            raise ValueError("ASR JSON 中未找到 text 或有效 segments 全文")

        # 语言来源
        lang_source = node_config.get("langSource", "from_asr")
        if lang_source == "manual":
            lang = (node_config.get("manualLang") or "").strip().lower()
        elif lang_source == "from_input":
            lang = self._resolve_input_language(task_dir)
        else:
            lang = (asr.get("language") or "").strip().lower()
        if not lang or lang == "auto":
            lang = "zh"
        puncts = self._load_puncts(lang)

        max_chars = 2000
        try:
            max_chars = int(node_config.get("maxChars", 2000))
        except (TypeError, ValueError):
            pass
        max_chars = max(200, max_chars)

        chunks = self._split_chunks(text, max_chars, puncts)
        if callback:
            callback(10, f"分批次：{len(chunks)} 段，语言={lang}，上限={max_chars}字")

        llm = get_llm_client()
        repaired_parts = []
        total = len(chunks)
        for idx, core in enumerate(chunks):
            if cancel_callback and cancel_callback():
                break
            prefix = chunks[idx - 1][-30:] if idx > 0 else ""
            suffix = chunks[idx + 1][:30] if idx + 1 < total else ""

            # 优先使用前端「Prompt 工程」可编辑的模板（ai_punctuate），缺失时回退内置提示
            from backend.prompts.prompt_service import get_prompt_service
            svc = get_prompt_service()
            assembled = svc.assemble_prompt("ai_punctuate", {
                "prefix": prefix,
                "core": core,
                "suffix": suffix,
            })
            if assembled.get("found"):
                system_prompt = assembled.get("system_prompt") or _SYSTEM_PROMPT
                user = assembled.get("user_prompt") or ""
            else:
                system_prompt = _SYSTEM_PROMPT
                user = ""
                if prefix:
                    user += f"【前文上下文，仅作理解参考，不要修改】\n{prefix}\n\n"
                user += f"【目标段落，请补全并修复其标点符号】\n{core}"
                if suffix:
                    user += f"\n\n【后文上下文，仅作理解参考，不要修改】\n{suffix}"

            try:
                result = llm.chat(
                    step_name="ai_punctuate",
                    prompt=user,
                    response_json=False,
                    stream=False,
                    log=True,
                    system_prompt=system_prompt,
                )
            except Exception as e:
                raise RuntimeError(f"LLM 标点补全请求失败：{e}") from e

            repaired = result if isinstance(result, str) else str(result)
            repaired_parts.append(self._extract_core(repaired, prefix, core))

            if callback:
                callback(int(10 + (idx + 1) / total * 85), f"标点补全 {idx + 1}/{total}")

        new_text = "".join(repaired_parts)

        asr["text"] = new_text
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        node_id = getattr(self, "_node_id", "unknown")
        out_name = f"asr_punctuated_{node_id}.json"
        out_path = os.path.join(out_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(asr, f, ensure_ascii=False, indent=2)

        # 修复全文同步保存为 TXT 文档（与 JSON 同名不同扩展名，便于阅读/下载）
        txt_name = f"asr_punctuated_{node_id}.txt"
        txt_path = os.path.join(out_dir, txt_name)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(new_text)

        if callback:
            callback(100, f"标点补全完成 -> {out_name} / {txt_name}")

        return {
            "artifacts": [f"output/{out_name}", f"output/{txt_name}"],
            "outputs": {
                "output": f"output/{out_name}",
                "text": f"output/{txt_name}",
            },
        }


StepAiPunctuate = S_AiPunctuate
