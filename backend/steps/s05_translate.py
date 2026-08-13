"""s05_translate: Translate sentences via LLM with faithful + reflective two-step process."""
import os
import json
import re
from typing import Callable, Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.llm.llm_client import get_llm_client


class S05Translate(BaseStep):
    step_id = "s05_translate"
    step_name = "逐句翻译"
    dependencies = ["s04_summarize"]
    artifacts = ["cache/translation_direct.json", "cache/translation_reflect.json"]

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_param(self, key: str, default=None):
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is not None and val != "":
            return val
        val = config.get(f"general.{key}")
        return val if val is not None else default

    def _resolve_target_language(self) -> str:
        node_cfg = getattr(self, "_node_config", {}) or {}
        lang = node_cfg.get("target_language") or config.get("general.target_language")
        return lang or "en"

    def _resolve_reflect_mode(self) -> bool:
        mode = self._get_param("reflect_translate", "follow_global")
        if mode == "yes":
            return True
        if mode == "no":
            return False
        # follow_global
        global_val = config.get("general.reflect_translate")
        if isinstance(global_val, bool):
            return global_val
        if isinstance(global_val, str):
            return global_val.lower() in ("yes", "true", "1")
        return True

    def _resolve_languages_from_input(self, task_dir: str):
        """Read source_language and target_language from input node in workflow.json."""
        src_lang = "auto"
        tgt_lang = "en"
        wf_path = os.path.join(task_dir, "workflow.json")
        if os.path.exists(wf_path):
            try:
                with open(wf_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                for node in wf.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        cfg = node.get("data", {}).get("config", {})
                        src = cfg.get("source_language", "")
                        tgt = cfg.get("target_language", "")
                        if src and src != "auto":
                            src_lang = src
                        if tgt:
                            tgt_lang = tgt
                        break
            except Exception:
                pass
        return src_lang, tgt_lang

    def _resolve_batch_char_limit(self) -> int:
        """Resolve batch char limit: prefer node config batch_char_limit,
        fallback to global llm.max_request_chars, then default 2000."""
        node_cfg = getattr(self, "_node_config", {}) or {}
        node_limit = node_cfg.get("batch_char_limit")
        if node_limit is not None and node_limit != "":
            try:
                return int(node_limit)
            except (ValueError, TypeError):
                pass
        global_limit = config.get("llm.max_request_chars")
        if global_limit is not None:
            try:
                return int(global_limit)
            except (ValueError, TypeError):
                pass
        return 2000

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_faithful_prompt(
        src_lang: str,
        tgt_lang: str,
        summary: str,
        terminology: List[Dict[str, str]],
        batch_sentences: List[Dict[str, Any]],
        style_hint: str,
        context_sentences: List[Dict[str, Any]],
    ) -> dict:
        term_lines = "\n".join(
            f"- {t['term']}: {t['explanation']}" for t in (terminology or [])
        )
        context_block = ""
        if context_sentences:
            context_lines = "\n".join(
                f"[{s['id']}] {s['text']}" for s in context_sentences
            )
            context_block = (
                f"\nPrevious sentences for context:\n{context_lines}\n"
            )

        style_block = ""
        if style_hint:
            style_block = f"\nTranslation style preference: {style_hint}\n"

        lines = "\n".join(
            f"[{s['id']}] {s['text']}" for s in batch_sentences
        )

        # Try to use JSON template via prompt service
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s05_translate_faithful", {
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "summary": summary[:500],
            "term_lines": term_lines or "(none)",
            "style_block": style_block,
            "context_block": context_block,
            "lines": lines,
            "batch_count": len(batch_sentences),
            "raw_terminology": terminology or [],
            "raw_lines": batch_sentences,
            "raw_context": context_sentences or [],
        })
        if result.get("found"):
            return {
                "system_prompt": result.get("system_prompt") or "You are a professional Netflix subtitle translator.",
                "user_prompt": result.get("user_prompt")
            }
        
        # Fallback to hardcoded prompt
        return {
            "system_prompt": "You are a professional Netflix subtitle translator.",
            "user_prompt": (
                f"Translate the following lines from {src_lang} to {tgt_lang}.\n\n"
                f"Summary of the video content (for context only, do not translate):\n"
                f"{summary[:500]}\n\n"
                f"Terminology table:\n{term_lines or '(none)'}\n"
                f"{style_block}"
                f"{context_block}"
                f"Translate each line faithfully — preserve the original meaning precisely.\n\n"
                f"CRITICAL RULES:\n"
                f"1. Every input sentence MUST have its own separate translation entry in the output.\n"
                f"2. NEVER merge multiple sentences into one translation. Each ID maps to exactly one translation.\n"
                f"3. NEVER leave any translation empty or blank. Every sentence must be translated.\n"
                f"4. The output JSON must have EXACTLY {len(batch_sentences)} entries, matching the input count.\n\n"
                f"Lines to translate:\n{lines}\n\n"
                f"Return a JSON object with integer keys matching the sentence IDs.\n"
                f'Each value should be an object: {{"origin": "original text", "direct": "direct translation"}}.\n'
                f"Example: {{1: {{\"origin\": \"Hello\", \"direct\": \"你好\"}}}}\n"
                f"Return ONLY the JSON object, no extra text."
            )
        }

    @staticmethod
    def _build_reflective_prompt(
        src_lang: str,
        tgt_lang: str,
        summary: str,
        terminology: List[Dict[str, str]],
        batch_sentences: List[Dict[str, Any]],
        faithful_results: Dict[int, Dict[str, str]],
        style_hint: str,
        context_sentences: List[Dict[str, Any]],
    ) -> dict:
        term_lines = "\n".join(
            f"- {t['term']}: {t['explanation']}" for t in (terminology or [])
        )
        context_block = ""
        if context_sentences:
            context_lines = "\n".join(
                f"[{s['id']}] {s['text']}" for s in context_sentences
            )
            context_block = (
                f"\nPrevious sentences for context:\n{context_lines}\n"
            )

        style_block = ""
        if style_hint:
            style_block = f"\nTranslation style preference: {style_hint}\n"

        translated_lines = ""
        for s in batch_sentences:
            sid = s["id"]
            fr = faithful_results.get(sid, {})
            translated_lines += (
                f"[{sid}] origin: {fr.get('origin', s['text'])}\n"
                f"     direct: {fr.get('direct', '')}\n"
            )

        # Try to use JSON template via prompt service
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s05_translate_reflect", {
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "summary": summary[:500],
            "term_lines": term_lines or "(none)",
            "style_block": style_block,
            "context_block": context_block,
            "translated_lines": translated_lines,
            "batch_count": len(batch_sentences),
            "raw_terminology": terminology or [],
            "raw_lines": batch_sentences,
            "raw_faithful_results": faithful_results,
            "raw_context": context_sentences or [],
        })
        if result.get("found"):
            return {
                "system_prompt": result.get("system_prompt") or "You are a professional Netflix subtitle translator and editor.",
                "user_prompt": result.get("user_prompt")
            }
        
        # Fallback to hardcoded prompt
        return {
            "system_prompt": "You are a professional Netflix subtitle translator and editor.",
            "user_prompt": (
                f"You previously produced direct/faithful translations from {src_lang} to {tgt_lang}.\n"
                f"Now review and improve them for natural expressiveness in the target language.\n\n"
                f"Summary (for context only):\n{summary[:500]}\n\n"
                f"Terminology table:\n{term_lines or '(none)'}\n"
                f"{style_block}"
                f"{context_block}"
                f"Previous direct translations:\n{translated_lines}\n"
                f"For each sentence, provide:\n"
                f"- origin: the original text\n"
                f"- direct: the direct translation (unchanged)\n"
                f"- reflection: a brief note on what could be improved\n"
                f"- free: an improved, more natural translation\n\n"
                f"CRITICAL RULES:\n"
                f"1. Every input sentence MUST have its own separate translation entry in the output.\n"
                f"2. NEVER merge multiple sentences into one translation. Each ID maps to exactly one translation.\n"
                f"3. NEVER leave the 'free' field empty or blank. Every sentence must have an improved translation.\n"
                f"4. The output JSON must have EXACTLY {len(batch_sentences)} entries, matching the input count.\n\n"
                f"Return a JSON object with integer keys matching the sentence IDs.\n"
                f'Each value: {{"origin", "direct", "reflection", "free"}}\n'
                f"Example: {{1: {{\"origin\": \"Hello\", \"direct\": \"你好\", \"reflection\": \"Could be more natural\", \"free\": \"嘿你好\"}}}}\n"
                f"Return ONLY the JSON object, no extra text."
            )
        }

    # ------------------------------------------------------------------
    # Batching
    # ------------------------------------------------------------------

    @staticmethod
    def _build_batches(sentences: List[Dict], batch_char_limit: int) -> List[Dict]:
        batches: List[Dict] = []
        current: List[Dict] = []
        current_len = 0
        for s in sentences:
            text_len = len(s.get("text", ""))
            if current and current_len + text_len > batch_char_limit:
                batches.append({
                    "index": len(batches),
                    "sentences": list(current),
                })
                current = []
                current_len = 0
            current.append({"id": s["id"], "text": s.get("text", "")})
            current_len += text_len
        if current:
            batches.append({
                "index": len(batches),
                "sentences": list(current),
            })
        return batches

    # ------------------------------------------------------------------
    # Validation & retry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response_to_map(result: Any) -> Dict[int, Dict]:
        """Parse LLM response into int-keyed dict, skipping invalid entries."""
        if not isinstance(result, dict):
            return {}
        parsed: Dict[int, Dict] = {}
        for key, val in result.items():
            try:
                int_key = int(key)
            except (ValueError, TypeError):
                continue
            if isinstance(val, dict):
                parsed[int_key] = val
        return parsed

    @staticmethod
    def _is_translation_empty(translation: str) -> bool:
        """Check if a translation text is effectively empty."""
        if not translation:
            return True
        stripped = translation.strip()
        if not stripped:
            return True
        # Check if it's just punctuation or whitespace
        if re.match(r'^[\s\W]+$', stripped):
            return True
        return False

    def _collect_missing_ids(
        self,
        expected_ids: List[int],
        result_map: Dict[int, Dict],
        field: str = "direct",
    ) -> List[int]:
        """Find sentence IDs whose translation is missing or empty."""
        missing = []
        for sid in expected_ids:
            entry = result_map.get(sid)
            if not entry:
                missing.append(sid)
                continue
            text = entry.get(field, "")
            if self._is_translation_empty(text):
                missing.append(sid)
        return missing

    def _retry_missing_translations(
        self,
        llm,
        missing_ids: List[int],
        sentences_by_id: Dict[int, Dict],
        src_lang: str,
        tgt_lang: str,
        summary: str,
        terminology: List[Dict],
        style_hint: str,
        field: str,
        phase: str,
        original_map: Dict[int, Dict],
    ) -> Dict[int, Dict]:
        """Retry translation for missing/empty entries and merge into original_map."""
        if not missing_ids:
            return original_map

        retry_sents = [sentences_by_id[sid] for sid in missing_ids if sid in sentences_by_id]
        if not retry_sents:
            return original_map

        print(f"[Translate] Retrying {len(retry_sents)} empty {phase} translations: {missing_ids}")

        # Build retry batch
        retry_batch = {
            "index": 0,
            "sentences": [{"id": s["id"], "text": s.get("text", "")} for s in retry_sents],
        }

        if phase == "faithful":
            prompt_data = self._build_faithful_prompt(
                src_lang, tgt_lang, summary, terminology,
                retry_batch["sentences"], style_hint, [],
            )
        else:
            # For reflective retry, build faithful data from what we have
            faithful_for_retry = {}
            for sid in missing_ids:
                orig_entry = original_map.get(sid, {})
                faithful_for_retry[sid] = {
                    "origin": sentences_by_id.get(sid, {}).get("text", ""),
                    "direct": orig_entry.get("direct", ""),
                }
            prompt_data = self._build_reflective_prompt(
                src_lang, tgt_lang, summary, terminology,
                retry_batch["sentences"], faithful_for_retry, style_hint, [],
            )

        try:
            retry_step_name = f"s05_translate_{phase}"
            result = llm.chat(
                retry_step_name, 
                prompt_data["user_prompt"], 
                system_prompt=prompt_data["system_prompt"],
                response_json=True
            )
            retry_map = self._parse_response_to_map(result)

            # Validate retry results
            still_missing = []
            for sid in missing_ids:
                entry = retry_map.get(sid)
                if entry:
                    text = entry.get(field, "")
                    if not self._is_translation_empty(text):
                        # Merge successful retry into original map
                        if sid not in original_map:
                            original_map[sid] = {}
                        original_map[sid].update(entry)
                        print(f"[Translate] Retry success for [{sid}] {phase}: '{text[:50]}...'")
                    else:
                        still_missing.append(sid)
                else:
                    still_missing.append(sid)

            if still_missing:
                print(f"[Translate] Warning: {len(still_missing)} {phase} translations still empty after retry: {still_missing}")
        except Exception as e:
            print(f"[Translate] Retry for {phase} failed: {e}")

        return original_map

    # ------------------------------------------------------------------
    # Single-batch worker (thread-safe)
    # ------------------------------------------------------------------

    def _translate_batch(
        self,
        llm,
        batch: Dict,
        src_lang: str,
        tgt_lang: str,
        summary: str,
        terminology: List[Dict],
        style_hint: str,
        prev_context: List[Dict],
        enable_reflect: bool,
    ) -> Dict:
        batch_id = batch["index"]
        batch_sents = batch["sentences"]
        expected_ids = [s["id"] for s in batch_sents]

        # --- Step 1: Faithful translation ---
        faithful_prompt_data = self._build_faithful_prompt(
            src_lang, tgt_lang, summary, terminology, batch_sents, style_hint, prev_context
        )
        faithful_result = llm.chat(
            "s05_translate_faithful", 
            faithful_prompt_data["user_prompt"], 
            system_prompt=faithful_prompt_data["system_prompt"],
            response_json=True
        )
        if not isinstance(faithful_result, dict):
            raise ValueError(
                f"Translate faithful batch {batch_id} returned non-dict response"
            )

        faithful_map = self._parse_response_to_map(faithful_result)

        # Validate faithful results — retry missing/empty entries
        missing_faithful = self._collect_missing_ids(expected_ids, faithful_map, "direct")
        if missing_faithful:
            sentences_by_id = {s["id"]: s for s in batch_sents}
            faithful_map = self._retry_missing_translations(
                llm, missing_faithful, sentences_by_id,
                src_lang, tgt_lang, summary, terminology, style_hint,
                field="direct", phase="faithful", original_map=faithful_map,
            )

        # --- Step 2: Reflective translation (if enabled) ---
        if enable_reflect:
            reflect_prompt_data = self._build_reflective_prompt(
                src_lang, tgt_lang, summary, terminology, batch_sents,
                faithful_map, style_hint, prev_context,
            )
            reflect_result = llm.chat(
                "s05_translate_reflect", 
                reflect_prompt_data["user_prompt"], 
                system_prompt=reflect_prompt_data["system_prompt"],
                response_json=True
            )
            if not isinstance(reflect_result, dict):
                raise ValueError(
                    f"Translate reflect batch {batch_id} returned non-dict response"
                )

            reflect_map = self._parse_response_to_map(reflect_result)

            # Validate reflect results — retry missing/empty entries
            missing_reflect = self._collect_missing_ids(expected_ids, reflect_map, "free")
            if missing_reflect:
                sentences_by_id = {s["id"]: s for s in batch_sents}
                reflect_map = self._retry_missing_translations(
                    llm, missing_reflect, sentences_by_id,
                    src_lang, tgt_lang, summary, terminology, style_hint,
                    field="free", phase="reflect", original_map=reflect_map,
                )
        else:
            reflect_map = {}

        return {
            "faithful": faithful_map,
            "reflect": reflect_map,
        }

    # ------------------------------------------------------------------
    # BaseStep interface
    # ------------------------------------------------------------------

    def check_artifact(self, task_dir: str) -> bool:
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        return all(os.path.exists(os.path.join(task_dir, "cache", f"{name}{node_suffix}.json"))
                   for name in ("translation_direct", "translation_reflect"))

    def validate_inputs(self, task_dir: str) -> bool:
        sentences_path = find_artifact(os.path.join(task_dir, "cache"), "sentences.json")
        summarize_path = find_artifact(os.path.join(task_dir, "cache"), "summarize_result.json")
        return sentences_path is not None and summarize_path is not None

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Loading inputs...")
        node_suffix = f"_{self._node_id}" if self._node_id else ""

        # Load inputs
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        sentences_path = step_inputs.get("subtitle") or find_artifact(os.path.join(task_dir, "cache"), "sentences.json")
        summarize_path = step_inputs.get("summary") or find_artifact(os.path.join(task_dir, "cache"), "summarize_result.json")
        if not sentences_path:
            raise FileNotFoundError("sentences.json not found in cache directory")
        if not summarize_path:
            raise FileNotFoundError("summarize_result.json not found in cache directory")
        if not os.path.isabs(sentences_path):
            sentences_path = os.path.join(task_dir, sentences_path)
        if not os.path.isabs(summarize_path):
            summarize_path = os.path.join(task_dir, summarize_path)

        with open(sentences_path, "r", encoding="utf-8") as f:
            sentences = json.load(f)
        with open(summarize_path, "r", encoding="utf-8") as f:
            summarize_data = json.load(f)

        if not sentences:
            if callback:
                callback(100, "No sentences to translate")
            out_path = os.path.join(task_dir, "cache", f"translation_direct{node_suffix}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return {
                "artifacts": [f"cache/translation_direct{node_suffix}.json", f"cache/translation_reflect{node_suffix}.json"],
                "outputs": {
                    "subtitle": f"cache/translation_direct{node_suffix}.json",
                    "reflect": f"cache/translation_reflect{node_suffix}.json",
                },
            }

        summary = summarize_data.get("summary", "")
        terminology = summarize_data.get("terminology", [])

        # Read languages from input node first, then fallback
        src_from_input, tgt_from_input = self._resolve_languages_from_input(task_dir)
        src_lang = src_from_input if src_from_input != "auto" else (self._get_param("source_language") or "auto")
        tgt_lang = tgt_from_input or self._resolve_target_language()
        enable_reflect = self._resolve_reflect_mode()

        # Resolve batch char limit: prefer global llm.max_request_chars
        batch_char_limit = self._resolve_batch_char_limit()
        # Reflective translation prompt is ~2x larger (includes faithful results),
        # so use a smaller batch size to avoid timeout
        reflect_batch_limit = batch_char_limit // 2 if enable_reflect else batch_char_limit
        style_hint = self._get_param("translation_style", "") or ""

        print(f"[Translate] Languages: {src_lang} -> {tgt_lang}, reflect={enable_reflect}, "
              f"batch_limit={batch_char_limit}, reflect_batch_limit={reflect_batch_limit}")

        if callback:
            callback(10, f"Building batches (limit={batch_char_limit} chars)...")

        batches = self._build_batches(sentences, reflect_batch_limit)
        total_batches = len(batches)

        if callback:
            callback(15, f"Created {total_batches} batches, starting translation...")

        llm = get_llm_client()
        max_workers = config.get("llm.max_concurrent") or 10

        # Build context mapping: prev_context for each batch
        # (last 2 sentences of previous batch)
        context_map: Dict[int, List[Dict]] = {0: []}
        for i in range(1, total_batches):
            prev_batch = batches[i - 1]["sentences"]
            context_map[i] = prev_batch[-2:] if len(prev_batch) >= 2 else prev_batch

        # Translate batches concurrently
        batch_results: Dict[int, Dict] = {}

        def _worker(batch: Dict) -> tuple:
            idx = batch["index"]
            result = self._translate_batch(
                llm, batch, src_lang, tgt_lang, summary, terminology,
                style_hint, context_map.get(idx, []), enable_reflect,
            )
            return idx, result

        try:
            with ThreadPoolExecutor(max_workers=min(max_workers, total_batches)) as executor:
                futures = {executor.submit(_worker, b): b["index"] for b in batches}
                done_count = 0
                for future in as_completed(futures):
                    try:
                        idx, result = future.result()
                        batch_results[idx] = result
                    except Exception as e:
                        batch_idx = futures[future]
                        raise RuntimeError(f"Translate batch {batch_idx} failed: {e}") from e
                    done_count += 1
                    if callback:
                        pct = int(15 + 75 * done_count / total_batches)
                        callback(min(pct, 90), f"Translated {done_count}/{total_batches} batches")
        except RuntimeError as e:
            if "cannot schedule new futures" in str(e) or "interpreter shutdown" in str(e):
                print("[Translate] ThreadPoolExecutor unavailable (interpreter shutting down), falling back to sequential execution")
                done_count = 0
                for b in batches:
                    idx, result = _worker(b)
                    batch_results[idx] = result
                    done_count += 1
                    if callback:
                        pct = int(15 + 75 * done_count / total_batches)
                        callback(min(pct, 90), f"Translated {done_count}/{total_batches} batches (sequential)")
            else:
                raise

        if callback:
            callback(92, "Assembling final results...")

        # Assemble output: preserve original sentence structure with added fields
        direct_output: List[Dict] = []
        reflect_output: List[Dict] = []

        # Build a flat map for faster lookup
        all_faithful: Dict[int, Dict] = {}
        all_reflect: Dict[int, Dict] = {}
        for result in batch_results.values():
            all_faithful.update(result.get("faithful", {}))
            all_reflect.update(result.get("reflect", {}))

        # Final validation: collect still-missing IDs after all retries
        all_ids = [s["id"] for s in sentences]
        missing_direct = self._collect_missing_ids(all_ids, all_faithful, "direct")
        missing_reflect_ids = self._collect_missing_ids(all_ids, all_reflect, "free") if enable_reflect else []

        if missing_direct:
            print(f"[Translate] WARNING: {len(missing_direct)} direct translations still empty after all retries: {missing_direct}")
        if missing_reflect_ids:
            print(f"[Translate] WARNING: {len(missing_reflect_ids)} reflect translations still empty after all retries: {missing_reflect_ids}")

        for s in sentences:
            sid = s["id"]
            # Base item without word-level timestamps
            base_item = {k: v for k, v in s.items() if k != "words"}

            # Find direct translation
            direct_entry = all_faithful.get(sid, {})
            direct_text = direct_entry.get("direct", "")

            # Find reflect translation
            reflect_text = ""
            if enable_reflect:
                reflect_entry = all_reflect.get(sid, {})
                reflect_text = reflect_entry.get("free", "")

            # Direct output: original + direct translation
            d_item = dict(base_item)
            d_item["direct"] = direct_text
            direct_output.append(d_item)

            # Reflect output: original + direct + reflect translation
            r_item = dict(base_item)
            r_item["direct"] = direct_text
            r_item["reflect"] = reflect_text
            reflect_output.append(r_item)

        # Save direct translation
        direct_path = os.path.join(task_dir, "cache", f"translation_direct{node_suffix}.json")
        with open(direct_path, "w", encoding="utf-8") as f:
            json.dump(direct_output, f, ensure_ascii=False, indent=2)

        # Save reflect translation
        reflect_path = os.path.join(task_dir, "cache", f"translation_reflect{node_suffix}.json")
        with open(reflect_path, "w", encoding="utf-8") as f:
            json.dump(reflect_output, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"Translation completed: {len(direct_output)} sentences")

        return {
            "artifacts": [f"cache/translation_direct{node_suffix}.json", f"cache/translation_reflect{node_suffix}.json"],
            "outputs": {
                "subtitle": f"cache/translation_direct{node_suffix}.json",
                "reflect": f"cache/translation_reflect{node_suffix}.json",
            },
        }
