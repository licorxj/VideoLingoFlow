"""s04_summarize: Summarize text and extract terminology via LLM."""
import os
import json
from typing import Callable, Optional
from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config


class S04Summarize(BaseStep):
    step_id = "s04_summarize"
    step_name = "内容总结"
    dependencies = ["s03_sentence_split"]
    artifacts = ["cache/summarize_result.json"]

    def check_artifact(self, task_dir: str) -> bool:
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        return os.path.exists(os.path.join(task_dir, "cache", f"summarize_result{node_suffix}.json"))

    def validate_inputs(self, task_dir: str) -> bool:
        return find_artifact(os.path.join(task_dir, "cache"), "sentences_text.txt") is not None

    def _get_param(self, key: str, default=None):
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is not None and val != "":
            return val
        val = config.get(f"general.{key}")
        return val if val is not None else default

    def _load_input_text(self, task_dir: str) -> str:
        """Load sentences_text.txt and join lines into a single text block."""
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        txt_path = step_inputs.get("text") or find_artifact(os.path.join(task_dir, "cache"), "sentences_text.txt")
        if not txt_path:
            raise FileNotFoundError("sentences_text.txt not found in cache directory")
        if not os.path.isabs(txt_path):
            txt_path = os.path.join(task_dir, txt_path)
        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        text = " ".join(line.strip() for line in lines if line.strip())
        return text

    def _build_prompt(self, text: str, max_summary_length: int) -> dict:
        # Try to use JSON template via prompt service
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s04_summarize", {
            "length": max_summary_length,
            "text": text[:8000],
        })
        if result.get("found"):
            return {
                "system_prompt": result.get("system_prompt"),
                "user_prompt": result.get("user_prompt")
            }
        
        # Fallback to hardcoded prompt
        return {
            "system_prompt": "You are a professional content summarizer.",
            "user_prompt": (
                "Given the following transcribed text from a video, produce:\n"
                "1. A concise summary of the content (at most {length} characters).\n"
                "2. A terminology table: extract domain-specific terms, proper nouns, "
                "and key concepts. For each term, provide the original term and its "
                "explanation/translation.\n\n"
                "Return a JSON object with exactly this format:\n"
                '{{\n'
                '  "summary": "your summary text here",\n'
                '  "terminology": [\n'
                '    {{"term": "Term1", "explanation": "Explanation1"}},\n'
                '    {{"term": "Term2", "explanation": "Explanation2"}}\n'
                '  ]\n'
                '}}\n\n'
                "Text to summarize:\n"
                "{text}"
            ).format(length=max_summary_length, text=text[:8000])
        }

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Loading input text...")

        node_config = getattr(self, "_node_config", {}) or {}
        max_summary_length = int(self._get_param("summary_length", 3000))
        text = self._load_input_text(task_dir)

        if not text.strip():
            raise ValueError("Input text is empty")

        if callback:
            callback(20, "Calling LLM for summarization...")

        from backend.llm.llm_client import get_llm_client

        llm = get_llm_client()
        # prompt 构建是本地处理（模板渲染），失败与 LLM 请求无关：
        # 直接抛出真实错误，不进入 LLM 请求重试链路
        try:
            prompt_data = self._build_prompt(text, max_summary_length)
        except Exception as e:
            print(f"[s04_summarize] prompt build failed (non-LLM error, no retry): {e}", flush=True)
            raise
        system_prompt = prompt_data.get("system_prompt") or ""
        user_prompt = prompt_data.get("user_prompt") or ""
        if not user_prompt.strip():
            raise RuntimeError(
                "[s04_summarize] prompt built empty (non-LLM error): "
                "check the s04_summarize prompt template"
            )
        print(
            f"[s04_summarize] prompt ready: input_text={len(text)} chars "
            f"(sent to LLM capped at 8000), user_prompt={len(user_prompt)} chars, "
            f"system_prompt={len(system_prompt)} chars",
            flush=True,
        )
        result = llm.chat(
            "s04_summarize",
            user_prompt,
            system_prompt=system_prompt,
            response_json=True
        )
        if not isinstance(result, dict):
            raise ValueError("Summarize LLM returned non-dict response")

        summary = result.get("summary", "")
        terms = result.get("terminology", [])
        if not isinstance(terms, list):
            raise ValueError("Summarize LLM returned invalid terminology list")

        # 合并自定义术语表
        use_custom = node_config.get("use_custom_terminology", False)
        custom_file = (node_config.get("custom_terminology_file") or "").strip()
        if use_custom and custom_file:
            custom_path = custom_file if os.path.isabs(custom_file) else os.path.join(task_dir, custom_file)
            if os.path.exists(custom_path):
                try:
                    with open(custom_path, "r", encoding="utf-8") as f:
                        custom_data = json.load(f)
                    custom_terms = custom_data if isinstance(custom_data, list) else custom_data.get("terminology", [])
                    if isinstance(custom_terms, list) and custom_terms:
                        # 合并：自定义术语不覆盖LLM已有的同名术语
                        existing_keys = {t.get("term", "").lower() for t in terms if isinstance(t, dict)}
                        added = 0
                        for ct in custom_terms:
                            if isinstance(ct, dict) and ct.get("term", "").lower() not in existing_keys:
                                terms.append(ct)
                                existing_keys.add(ct.get("term", "").lower())
                                added += 1
                        print(f"[Summarize] Merged {added} custom terms (total {len(terms)})")
                except Exception as e:
                    print(f"[Summarize] Warning: Failed to load custom terminology: {e}")

        if callback:
            callback(70, "Saving results...")

        # Save result JSON
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        raw_path = os.path.join(task_dir, "cache", f"summarize_result{node_suffix}.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "terminology": terms}, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"Summary done: {len(summary)} chars, {len(terms)} terms")

        return {
            "artifacts": [f"cache/summarize_result{node_suffix}.json"],
            "outputs": {
                "subtitle": f"cache/summarize_result{node_suffix}.json",
            },
        }
