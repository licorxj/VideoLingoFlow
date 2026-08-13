"""s_translate_task_name: Translate the project/task name via LLM.
Optionally replace task.json's task_name with the translation.

Logic:
  1. If replace_task_name is enabled, read task_name from task.json.
  2. If no task_name, fall back to the input file's basename (from input_config).
  3. If neither is available, warn and skip.
  4. Translate via LLM with filename-safe rules.
  5. If replace_task_name is enabled, write the translated name back to task.json.
  6. Save translation to task_name.txt.
"""
import os
import json
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.llm.llm_client import get_llm_client
from backend.prompts.prompt_service import get_prompt_service


class S_TranslateTaskName(BaseStep):
    step_id = "translate_task_name"
    step_name = "翻译项目名称"
    dependencies = []
    artifacts = ["cache/task_name.txt"]

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.exists(os.path.join(task_dir, "cache", "task_name.txt"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        replace_task_name = node_config.get("replace_task_name", False)
        print(f"[TranslateTaskName] node_config keys: {list(node_config.keys())}, replace_task_name={replace_task_name!r} (type={type(replace_task_name).__name__})")

        # Read target language: step_inputs → workflow.json input node → "zh"
        target_language = step_inputs.get("target_language", "")
        if not target_language:
            wf_path = os.path.join(task_dir, "workflow.json")
            if os.path.exists(wf_path):
                try:
                    with open(wf_path, "r", encoding="utf-8") as f:
                        wf = json.load(f)
                    for node in wf.get("nodes", []):
                        if node.get("data", {}).get("nodeType") == "input":
                            lang = node.get("data", {}).get("config", {}).get("target_language", "")
                            if lang:
                                target_language = lang
                                break
                except Exception:
                    pass
        if not target_language:
            target_language = "zh"

        if callback:
            callback(10, "Loading task name...")

        # 1. Try task_name from task.json
        task_json_path = os.path.join(task_dir, "task.json")
        task_name = ""
        input_file_name = ""
        if os.path.exists(task_json_path):
            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                task_name = task_data.get("task_name", "") or ""
            except Exception:
                pass

        # 2. Fall back to input file name from input_config in task.json
        if not task_name:
            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    input_cfg = json.load(f).get("input", {})
                for key in ("videoPath", "audioPath", "subtitlePath", "url"):
                    val = input_cfg.get(key, "")
                    if val:
                        if val.startswith(("http://", "https://")):
                            from urllib.parse import urlparse, unquote
                            parsed = urlparse(val)
                            path_part = unquote(os.path.basename(parsed.path))
                            if path_part:
                                # 只获取文件名，去掉扩展名
                                input_file_name = os.path.splitext(path_part)[0]
                                break
                        else:
                            base = os.path.basename(val)
                            if base:
                                # 只获取文件名，去掉扩展名
                                input_file_name = os.path.splitext(base)[0]
                                break
            except Exception:
                pass
            if input_file_name:
                task_name = input_file_name

        # 3. Nothing to translate
        if not task_name:
            warning = "未找到任务名称或输入文件名，跳过翻译"
            print(f"[TranslateTaskName] {warning}")
            if callback:
                callback(100, warning)
            # Write empty output so downstream nodes have a file to reference
            out_path = os.path.join(task_dir, "cache", "task_name.txt")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("")
            return {
                "artifacts": ["cache/task_name.txt"],
                "outputs": {"text": out_path, "translated": ""},
            }

        # 3.5 去掉文件扩展名（如果 task_name 包含扩展名）
        if task_name and "." in task_name:
            # 检查是否是文件扩展名（最后一个点后面的部分是常见扩展名）
            name_parts = task_name.rsplit(".", 1)
            if len(name_parts) == 2 and len(name_parts[1]) <= 10:
                # 可能是扩展名，去掉它
                task_name = name_parts[0]
                print(f"[TranslateTaskName] 去掉扩展名: {task_name}")

        if callback:
            callback(30, f"Translating: {task_name}")

        # 4. Translate via LLM
        svc = get_prompt_service()
        prompt_bundle = svc.assemble_prompt("translate_task_name", {
            "text": task_name,
            "target_language": target_language
        })

        llm = get_llm_client()
        try:
            translated_name = llm.chat(
                step_name=self.step_id,
                prompt=prompt_bundle["user_prompt"],
                response_json=False,
                system_prompt=prompt_bundle["system_prompt"]
            )
            translated_name = (translated_name or "").strip().strip('"').strip("'")
        except Exception as e:
            translated_name = task_name  # Fallback to original
            print(f"[TranslateTaskName] LLM failed, using original name: {e}")

        if callback:
            callback(70, f"Translated: {translated_name}")

        # 5. Optionally replace task_name in task.json
        print(f"[TranslateTaskName] replace_task_name={replace_task_name!r}, translated_name={translated_name!r}")
        if replace_task_name and translated_name:
            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                old_name = task_data.get("task_name", "")
                task_data["task_name"] = translated_name
                with open(task_json_path, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=2)
                print(f"[TranslateTaskName] Updated task_name: {old_name} -> {translated_name}")
            except Exception as e:
                print(f"[TranslateTaskName] WARNING: failed to update task_name: {e}")
        else:
            print(f"[TranslateTaskName] SKIP writing task_name: condition not met")

        # 6. Save to task_name.txt
        out_path = os.path.join(task_dir, "cache", "task_name.txt")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(translated_name)

        if callback:
            callback(100, f"Done: {translated_name}")

        return {
            "artifacts": ["cache/task_name.txt"],
            "outputs": {"text": out_path, "translated": translated_name},
        }
