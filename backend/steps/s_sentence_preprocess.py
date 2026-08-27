"""s_sentence_preprocess: 断句预处理节点。

在进入 s03 句子分割之前，基于全文文本（而非 VAD 原生断句）产生更可靠的初始 segments。

支持三种断句方法：
  - asr  : 直接使用输入 ASR 结果中的 segments（ASR分段）
  - punct: 按语言标点对全文断句（标点符号断句）
  - ai   : LLM 按专业字幕组习惯对全文断句（AI断句）

输入（二选一）：
  - json 端口：ASR 格式 JSON（{language, text, segments:[{id,start,end,text,words}]}）
  - text 端口：长文本 TXT 文件

输出：
  - subtitle 端口：ASR 格式 JSON（含可选的句子级时间戳重建）
  - word_index 端口：压平的词级时间戳表 {index: {word,start,end,speaker}}
"""
import json
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

from backend.steps.base_step import BaseStep
from backend.config.config_manager import config

# AI 断句复用"句子分割"阶段模型（config.yaml llm.step_models.s03_sentence_split）
_LLM_STEP_NAME = "s03_sentence_split"


class S_SentencePreprocess(BaseStep):
    step_id = "sentence_preprocess"
    step_name = "断句预处理"
    dependencies = []
    # 固定输出名：与 ASR 节点同名，供下游节点作为时间点查询标准；
    # word_index 固定名，方便其他节点按文件名直接读取
    artifacts = ["cache/asr_result.json", "cache/word_index.json"]

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "") or ""
        name = f"asr_result_{node_id}.json" if node_id else "asr_result.json"
        return os.path.exists(os.path.join(task_dir, "cache", name))

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        for key in ("json", "text"):
            val = step_inputs.get(key, "")
            if val:
                p = val if os.path.isabs(val) else os.path.join(task_dir, val)
                if os.path.exists(p):
                    return True
        return False

    # ── 参数读取 ──────────────────────────────────────────────────

    def _get_param(self, key: str, default=None):
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is not None and val != "":
            return val
        val = config.get(f"general.{key}")
        return val if val is not None else default

    def _get_bool_param(self, key: str, default: bool) -> bool:
        val = self._get_param(key, default)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    def _get_int_param(self, key: str, default: int) -> int:
        val = self._get_param(key, default)
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default

    # ── 语言与标点 ────────────────────────────────────────────────

    def _resolve_language(self, task_dir: str, asr_data: Optional[dict]) -> str:
        """解析节点处理语言，from_input 时回退到输入节点和 ASR 结果。"""
        node_language = str((getattr(self, "_node_config", {}) or {}).get("processing_language") or "from_input").strip()
        if node_language not in ("", "from_input", "auto"):
            return node_language
        wf_path = os.path.join(task_dir, "workflow.json")
        if os.path.exists(wf_path):
            try:
                with open(wf_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                for node in wf.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        lang = node.get("data", {}).get("config", {}).get("source_language", "")
                        if lang and lang != "auto":
                            return lang
                        break
            except Exception:
                pass
        if asr_data:
            lang = asr_data.get("language", "")
            if lang and lang != "auto":
                return lang
        return "auto"

    def _load_language_puncts(self, lang: str = "auto") -> Dict[str, set]:
        """加载 language_puncts.json：精确语言 → 基础语言 → _default，并与 _common 合并。"""
        puncts_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "language_puncts.json"
        )
        try:
            with open(puncts_path, "r", encoding="utf-8") as f:
                all_puncts = json.load(f)
        except Exception:
            all_puncts = {}

        common = all_puncts.get("_common", {})
        common_ends = set(common.get("sentence_ends", []))
        common_breaks = set(common.get("clause_breaks", []))

        lang_base = lang.split("-")[0] if "-" in lang else lang
        entry = all_puncts.get(lang) or all_puncts.get(lang_base) or all_puncts.get("_default", {})
        return {
            "sentence_ends": set(entry.get("sentence_ends", [])) | common_ends,
            "clause_breaks": set(entry.get("clause_breaks", [])) | common_breaks,
        }

    @staticmethod
    def _is_part_of_number(text: str, pos: int) -> bool:
        """判断 pos 处的标点是否为数字的一部分（小数点/千分位），跳过不切分。"""
        if pos < 0 or pos >= len(text):
            return False
        ch = text[pos]
        if ch not in ".,，":
            return False
        digits = "0123456789０１２３４５６７８９"
        prev_ch = text[pos - 1] if pos > 0 else ""
        next_ch = text[pos + 1] if pos + 1 < len(text) else ""
        if prev_ch in digits and next_ch in digits:
            return True
        if prev_ch in digits:
            j = pos + 1
            while j < len(text) and text[j] in " \t":
                j += 1
            if j < len(text) and text[j] in digits:
                return True
        return False

    # ── 输入检查与信息打印（需求2） ────────────────────────────────

    def _load_input(self, task_dir: str) -> Tuple[str, Optional[dict], str]:
        """返回 (input_kind, asr_data_or_None, full_text)。json 输入优先于 text。"""
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        json_val = step_inputs.get("json", "")
        text_val = step_inputs.get("text", "")

        def _resolve_path(val: str) -> str:
            if not val:
                return ""
            p = val if os.path.isabs(val) else os.path.join(task_dir, val)
            return p if os.path.isfile(p) else ""

        json_path = _resolve_path(json_val)
        txt_path = _resolve_path(text_val)

        if json_path:
            with open(json_path, "r", encoding="utf-8") as f:
                asr_data = json.load(f)
            if not isinstance(asr_data, dict):
                raise ValueError("JSON 输入必须是对象（ASR 格式）")
            full_text = str(asr_data.get("text", "") or "")
            if not full_text.strip():
                seg_texts = [
                    str(s.get("text", "")) for s in asr_data.get("segments", [])
                    if str(s.get("text", "")).strip()
                ]
                full_text = " ".join(seg_texts)
            return "json", asr_data, full_text

        if txt_path:
            with open(txt_path, "r", encoding="utf-8") as f:
                full_text = f.read()
            return "txt", None, full_text

        raise ValueError("未连接输入：请在 'ASR结果JSON' 或 '长文本TXT' 端口接入上游数据")

    def _has_multi_speaker(self, asr_data: dict) -> bool:
        """段级或词级 speaker 中是否存在 >=2 个不同说话人。"""
        speakers = set()
        for seg in asr_data.get("segments", []) or []:
            sp = seg.get("speaker")
            if sp:
                speakers.add(sp)
            for w in seg.get("words", []) or []:
                ws = w.get("speaker")
                if ws:
                    speakers.add(ws)
        speakers = {s for s in speakers if s not in (None, "", "null", "None")}
        return len(speakers) >= 2

    @staticmethod
    def _has_word_timestamps(asr_data: dict) -> bool:
        for seg in asr_data.get("segments", []) or []:
            if seg.get("words"):
                return True
        return False

    # ── 说话人切割（需求4 前置） ───────────────────────────────────

    @staticmethod
    def _speaker_of_segment(seg: dict) -> str:
        sp = seg.get("speaker")
        if sp:
            return str(sp)
        for w in seg.get("words", []) or []:
            ws = w.get("speaker")
            if ws:
                return str(ws)
        return ""

    def _split_by_speaker(self, asr_data: dict) -> List[dict]:
        """按说话人把 segments 分组，输出 [{speaker, text}]，相邻同说话人合并。"""
        groups: List[dict] = []
        for seg in asr_data.get("segments", []) or []:
            sp = self._speaker_of_segment(seg)
            text = str(seg.get("text", "") or "").strip()
            if not text:
                continue
            if groups and groups[-1].get("speaker") == sp:
                groups[-1]["text"] += "\n" + text
            else:
                groups.append({"speaker": sp, "text": text})
        return groups

    # ── 断句方法实现（需求4） ─────────────────────────────────────

    def _split_punct(self, text: str, lang: str) -> List[Dict]:
        """标点符号断句：按句末标点切分；全文无标点时按换行断句。"""
        puncts = self._load_language_puncts(lang)
        ends = puncts["sentence_ends"]
        all_punct = ends | puncts["clause_breaks"]
        if not any(ch in text for ch in all_punct):
            print("[Preprocess] 输入文本不包含标点符号，将仅仅按照换行断句")
            return [{"text": line.strip(), "speaker": ""}
                    for line in text.splitlines() if line.strip()]

        chunks = []
        current = ""
        for i, ch in enumerate(text):
            current += ch
            if ch in ends and not self._is_part_of_number(text, i):
                chunks.append(current)
                current = ""
        if current.strip():
            chunks.append(current)
        return [{"text": c.strip(), "speaker": ""} for c in chunks if c.strip()]

    def _pre_segment_text(self, text: str, char_limit: int, lang: str) -> List[str]:
        """AI 断句前的预分段：在字数上限前 100 字符窗口内找切割点。

        切割点优先级：换行符 > 标点符号 > 空格；找不到则硬切兜底。
        """
        if char_limit <= 0:
            return [text]
        puncts = self._load_language_puncts(lang)
        punct_chars = puncts["sentence_ends"] | puncts["clause_breaks"]

        result: List[str] = []
        pos = 0
        n = len(text)
        while pos < n:
            end = min(pos + char_limit, n)
            if end >= n:
                result.append(text[pos:])
                break

            window_start = max(pos, end - 100)
            cut = -1
            # 1. 换行符（从窗口末尾往前找）
            for j in range(end - 1, window_start - 1, -1):
                if text[j] in "\n\r":
                    cut = j
                    break
            # 2. 标点符号
            if cut < 0:
                for j in range(end - 1, window_start - 1, -1):
                    if text[j] in punct_chars and not self._is_part_of_number(text, j):
                        cut = j
                        break
            # 3. 空格
            if cut < 0:
                for j in range(end - 1, window_start - 1, -1):
                    if text[j] in " \t":
                        cut = j
                        break
            if cut < 0:
                cut = end  # 硬切兜底

            result.append(text[pos:cut + 1].strip())
            pos = cut + 1
            while pos < n and text[pos] in " \t\n\r":
                pos += 1
        return [seg for seg in result if seg]

    def _build_ai_prompt(self, text: str, max_chars: int, lang: str) -> dict:
        """通过 prompt 服务组装 AI 断句 prompt；模板缺失时使用硬编码兜底。"""
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("sentence_preprocess", {
            "text": text,
            "max_chars": max_chars,
            "language": lang or "auto",
        })
        if result.get("found"):
            return {
                "system_prompt": result.get("system_prompt"),
                "user_prompt": result.get("user_prompt"),
            }
        return {
            "system_prompt": (
                "You are a professional subtitle-group segmentation expert.\n"
                "## CRITICAL RULES\n"
                "- STRICT TEXT PRESERVATION: output MUST be exactly the original text; "
                "do NOT modify, rephrase, add or drop ANY character.\n"
                "- Follow professional subtitle-group segmentation practices and the "
                "natural segmentation habits of the language.\n"
                "- Avoid awkward cuts and avoid overly long sentences.\n"
                "- Punctuation belongs to the preceding sentence; never start a segment "
                "with punctuation.\n"
                "- Never produce a segment that is only punctuation or only numbers.\n"
            ),
            "user_prompt": (
                "Split the following text into sentences.\n"
                "Each sentence must be AT MOST {max_chars} characters.\n"
                "Language: {language}\n"
                "## Text\n{text}\n"
                "## Output Format\n"
                "Return a JSON object mapping sentence index to sentence text, e.g. "
                '{{"0": "sentence1", "1": "sentence2"}}.\n'
                "The concatenation of all sentences must equal the input text exactly.\n"
                "Return ONLY the JSON object."
            ).format(max_chars=max_chars, language=lang or "auto", text=text),
        }

    def _split_ai(self, text: str, char_limit: int, lang: str,
                  callback: Optional[Callable]) -> List[Dict]:
        """AI 断句：预分段 → 并发 LLM 请求 → 解析拼接。"""
        from backend.llm.llm_client import get_llm_client

        segments = self._pre_segment_text(text, char_limit, lang)
        if callback:
            callback(50, f"AI 断句：预分段 {len(segments)} 段，并发请求中...")

        requests = []
        for seg in segments:
            prompt_data = self._build_ai_prompt(seg, char_limit, lang)
            requests.append({
                "step_name": _LLM_STEP_NAME,
                "prompt": prompt_data["user_prompt"],
                "system_prompt": prompt_data["system_prompt"],
                "response_json": True,
            })

        llm = get_llm_client()
        max_concurrent = int(config.get("llm.max_concurrent") or 10)
        results = llm.batch_chat(requests, max_workers=max_concurrent)

        sentences: List[str] = []
        for idx, res in enumerate(results):
            if isinstance(res, dict) and "error" in res:
                print(f"[Preprocess] 批次 {idx} LLM 请求失败: {res['error']}")
                continue
            if not isinstance(res, dict):
                print(f"[Preprocess] 批次 {idx} 返回非 dict: {type(res)}")
                continue
            items = []
            for k, v in res.items():
                if isinstance(v, str) and v.strip():
                    order = int(k) if str(k).isdigit() else len(items)
                    items.append((order, v.strip()))
            items.sort(key=lambda x: x[0])
            sentences.extend(t for _, t in items)

        if not sentences:
            raise ValueError("AI 断句未产生任何句子，请检查 LLM 配置")
        return [{"text": s, "speaker": ""} for s in sentences]

    # ── 时间戳重建（需求5） ───────────────────────────────────────

    def _build_word_index(self, asr_data: dict) -> Dict[str, dict]:
        """压平单词级时间戳为 {index: {word,start,end,speaker}}，去掉单独的纯标点项。"""
        puncts = self._load_language_puncts(asr_data.get("language", "auto"))
        all_puncts = puncts["sentence_ends"] | puncts["clause_breaks"]
        index: Dict[str, dict] = {}
        idx = 0
        for seg in asr_data.get("segments", []) or []:
            for w in seg.get("words", []) or []:
                word = str(w.get("word", "") or "").strip()
                if not word:
                    continue
                compact = re.sub(r"\s+", "", word)
                if compact and all(ch in all_puncts for ch in compact):
                    continue  # 去掉单独的纯标点项
                index[str(idx)] = {
                    "word": word,
                    "start": w.get("start", 0),
                    "end": w.get("end", 0),
                    "speaker": w.get("speaker", ""),
                }
                idx += 1
        return index

    def _align_sentences(self, segs: List[dict], full_text: str,
                         word_index: dict, asr_data: dict) -> List[dict]:
        """用全局字符锚点 + 插值重建每句时间轴（见 backend/utils/time_align.py）。

        替代旧的逐句子序列贪心匹配，避免稀疏词时间戳下的跨句抢词与游标漂移。
        """
        from backend.utils.time_align import SentenceTimeAligner
        word_list = list(word_index.values())
        aligner = SentenceTimeAligner(
            full_text, word_list, segments=asr_data.get("segments"))
        out = []
        for idx, s in enumerate(segs, start=1):
            matched, start, end = aligner.align_next(s["text"])
            out.append({
                "id": idx,
                "text": s["text"],
                "speaker": s.get("speaker", ""),
                "start": float(start or 0.0),
                "end": float(end or 0.0),
                "words": matched,
            })
        return out

    # ── 主流程（需求2-5） ─────────────────────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "") or ""
        if callback:
            callback(5, "加载输入与参数检查...")

        # A. 参数与输入检查（需求2）
        method = str(self._get_param("method", "ai") or "ai").strip().lower()
        split_on_speaker = self._get_bool_param("split_on_speaker", True)
        llm_max_chars = self._get_int_param("llm_max_chars", 0)

        input_kind, asr_data, full_text = self._load_input(task_dir)
        if input_kind == "txt" and method == "asr":
            print("[Preprocess] 警告：TXT 输入不支持 ASR 分段方法，已回退使用标点符号断句")
            method = "punct"

        lang = self._resolve_language(task_dir, asr_data)
        puncts = self._load_language_puncts(lang)
        all_punct_chars = puncts["sentence_ends"] | puncts["clause_breaks"]
        has_punct = any(ch in full_text for ch in all_punct_chars)

        has_multi = bool(asr_data) and self._has_multi_speaker(asr_data)
        has_segments = bool(asr_data) and bool(asr_data.get("segments"))
        has_words = bool(asr_data) and self._has_word_timestamps(asr_data)

        print(
            f"[Preprocess] 输入类型={input_kind}, 语言={lang}, 全文长度={len(full_text)}, "
            f"含标点={has_punct}, 多说话人={has_multi}, "
            f"asr_segments={has_segments}, 词级时间戳={has_words}"
        )
        if callback:
            callback(15, f"输入检查完成：类型={input_kind}，语言={lang}，全文 {len(full_text)} 字符")

        # B. 路由决策（需求3）
        if method == "asr" and not has_segments:
            print("[Preprocess] 输入不包含 ASR 分段数据（segments 为空），无法使用 ASR 分段，回退使用标点符号断句")
            method = "punct"

        if method == "asr":
            # 存在 asr_segments 且选择 ASR 分段 → 直接输出原始 ASR 结果
            output = dict(asr_data) if asr_data else {"language": lang, "segments": []}
            output["text"] = full_text  # 与原始 ASR 结果结构保持一致
            word_index_path = None
            if callback:
                callback(80, "ASR 分段方法：直接输出原始 ASR 结果")
        else:
            # 说话人切割（需求4 前置，仅 json 多说话人且勾选时生效）
            base_chunks = None
            if split_on_speaker and has_multi:
                if callback:
                    callback(25, "多人会话切割...")
                base_chunks = self._split_by_speaker(asr_data)
                print(f"[Preprocess] 多人会话切割：{len(base_chunks)} 个说话人片段")

            if method == "punct":
                if callback:
                    callback(35, "标点符号断句...")
                if base_chunks is None:
                    segs = self._split_punct(full_text, lang)
                else:
                    segs = []
                    for g in base_chunks:
                        for s in self._split_punct(g["text"], lang):
                            s["speaker"] = g["speaker"]
                            segs.append(s)
            else:  # ai
                char_limit = llm_max_chars if llm_max_chars > 0 else int(config.get("llm.max_request_chars") or 3000)
                print(f"[Preprocess] AI 断句：char_limit={char_limit}, max_concurrent={config.get('llm.max_concurrent')}")
                if callback:
                    callback(40, f"AI 断句（字数上限 {char_limit}）...")
                if base_chunks is None:
                    segs = self._split_ai(full_text, char_limit, lang, callback)
                else:
                    segs = []
                    for g in base_chunks:
                        for s in self._split_ai(g["text"], char_limit, lang, callback):
                            s["speaker"] = g["speaker"]
                            segs.append(s)

            # C/D. 时间戳重建与输出（需求5）
            if has_words:
                if callback:
                    callback(70, "重建句子级时间戳...")
                word_index = self._build_word_index(asr_data)
                word_index_path = os.path.join(
                    task_dir, "cache",
                    f"word_index_{node_id}.json" if node_id else "word_index.json")
                os.makedirs(os.path.dirname(word_index_path), exist_ok=True)
                with open(word_index_path, "w", encoding="utf-8") as f:
                    json.dump(word_index, f, ensure_ascii=False, indent=2)

                segments_out = self._align_sentences(segs, full_text, word_index, asr_data)
            else:
                word_index_path = None
                segments_out = [
                    {"id": idx, "text": s["text"], "speaker": s.get("speaker", "")}
                    for idx, s in enumerate(segs, start=1)
                ]

            output = {"language": lang, "text": full_text, "segments": segments_out}

        # 保存输出：文件名带节点 id 后缀（cache/asr_result_{node_id}.json），
        # 与 ASR 节点产物区分，避免相互覆盖；下游通过输入端口或 find_artifact 读取。
        main_name = f"asr_result_{node_id}.json" if node_id else "asr_result.json"
        main_path = os.path.join(task_dir, "cache", main_name)
        os.makedirs(os.path.dirname(main_path), exist_ok=True)
        with open(main_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        seg_count = len(output.get("segments", []))
        if callback:
            callback(100, f"断句预处理完成：{seg_count} 个句子")

        artifacts = [os.path.join("cache", main_name)]
        outputs = {"subtitle": os.path.join("cache", main_name)}
        if word_index_path:
            artifacts.append("cache/word_index.json")
            outputs["word_index"] = "cache/word_index.json"
        return {"artifacts": artifacts, "outputs": outputs}
