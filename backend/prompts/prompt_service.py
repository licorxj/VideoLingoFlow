"""
Prompt Service: renders prompt templates with live config values.
Supports hot-reload, language-aware rendering, and template preview.
Also supports JSON-based prompt template management for the Prompt Engineering UI.
"""
import copy
import json
import os
import re
import threading
import uuid
from typing import Any, Optional, Set
from jinja2 import Environment, meta, exceptions
from backend.config.config_manager import config


class PromptService:
    """Renders prompt templates with live config values."""

    def __init__(self):
        self._custom_templates_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "prompts"
        )
        os.makedirs(self._custom_templates_dir, exist_ok=True)
        self._json_templates_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "prompt_templates.json"
        )
        # 配音谷内置 Prompt 预设（只读种子源，用于补种与「恢复默认」）
        self._voiceforge_defaults_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "voiceforge_prompt_defaults.json"
        )
        self._json_cache = None
        self._json_lock = threading.Lock()
        
        # Initialize Jinja2 environment
        self.jinja_env = Environment(
            autoescape=False,  # Prompt templates don't need HTML escaping
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True
        )

    def _get_languages(self) -> dict:
        """Get current language settings from config."""
        return {
            "src_lang": config.get("general.source_language") or "auto",
            "tgt_lang": config.get("general.target_language") or "zh",
            "detected_lang": config.get("whisper.detected_language") or "en",
        }

    def list_steps(self) -> list[dict]:
        """List all steps that have prompt templates from JSON."""
        templates = self.load_json_templates()
        result = []
        for t in templates:
            result.append({
                "step_id": t.get("id"),
                "name": t.get("name"),
                "templates": ["default"],  # For backward compatibility with the old list_steps
            })
        return result

    def list_templates(self, step_id: str) -> list[str]:
        """List template names for a given step (JSON version)."""
        template = self.get_json_template_by_id(step_id)
        if template:
            return ["default"]
        return []

    def get_template(self, step_id: str, template_name: str = "default") -> Optional[str]:
        """Get raw template string from JSON."""
        template_data = self.get_json_template_by_id(step_id)
        if template_data:
            # For backward compatibility, return user_prompt as the main template
            return template_data.get("user_prompt")
        return None

    def save_custom_template(self, step_id: str, content: str):
        """Save a custom prompt template."""
        custom_file = os.path.join(self._custom_templates_dir, f"{step_id}.txt")
        with open(custom_file, "w", encoding="utf-8") as f:
            f.write(content)

    def render(
        self,
        step_id: str,
        template_name: str,
        params: Optional[dict] = None,
    ) -> str:
        """
        Render a prompt template with config values and custom params.

        Args:
            step_id: Step identifier (e.g., "s05_translate")
            template_name: Template name (e.g., "faithfulness")
            params: Additional parameters to inject into template

        Returns:
            Rendered prompt string
        """
        template = self.get_template(step_id, template_name)
        if not template:
            raise ValueError(f"Template not found: {step_id}/{template_name}")

        # Auto-inject language config
        lang = self._get_languages()
        render_params = {
            "src_lang": lang["detected_lang"] if lang["src_lang"] == "auto" else lang["src_lang"],
            "tgt_lang": lang["tgt_lang"],
        }

        # Auto-inject common config values
        render_params["max_sentence_length"] = config.get("general.max_sentence_length") or 100
        render_params["summary_length"] = config.get("general.summary_length") or 3000

        # Merge custom params (override defaults)
        if params:
            render_params.update(params)

        # Render with safe formatting (missing keys show as empty)
        try:
            return template.format(**render_params)
        except KeyError as e:
            # Try again with missing keys filled
            for key in render_params:
                template = template.replace("{" + key + "}", str(render_params[key]))
            return template

    def preview(
        self,
        step_id: str,
        template_name: str,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Preview a rendered prompt with metadata.

        Returns:
            {
                "step_id": str,
                "template_name": str,
                "rendered": str,
                "params_used": dict,
                "source_languages": dict,
            }
        """
        lang = self._get_languages()
        rendered = self.render(step_id, template_name, params)

        all_params = {
            "src_lang": lang["detected_lang"] if lang["src_lang"] == "auto" else lang["src_lang"],
            "tgt_lang": lang["tgt_lang"],
        }
        if params:
            all_params.update(params)

        return {
            "step_id": step_id,
            "template_name": template_name,
            "rendered": rendered,
            "params_used": all_params,
            "source_languages": lang,
        }

    # ================================================================
    # JSON-based Prompt Template Management (Prompt Engineering)
    # ================================================================

    def load_json_templates(self, scope: Optional[str] = None) -> list[dict]:
        """Load prompt templates from prompt_templates.json.

        scope 用于把 Prompt 预设限定在某个功能域（如 voiceforge 晴沐配音谷）。
        未传 scope 时返回全部；模板缺失 scope 时按 "global" 处理。
        """
        with self._json_lock:
            if self._json_cache is not None:
                templates = list(self._json_cache)
            elif not os.path.exists(self._json_templates_path):
                return []
            else:
                with open(self._json_templates_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._json_cache = data.get("templates", [])
                templates = list(self._json_cache)
        if scope:
            return [t for t in templates if (t.get("scope") or "global") == scope]
        return templates

    # ── 配音谷 Prompt 预设（scope=voiceforge）──────────────────────

    def load_voiceforge_defaults(self) -> list[dict]:
        """读取配音谷内置预设种子（只读，不写入缓存）。"""
        if not os.path.exists(self._voiceforge_defaults_path):
            return []
        try:
            with open(self._voiceforge_defaults_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        return data.get("templates", [])

    def seed_voiceforge_defaults(self) -> int:
        """补种缺失的配音谷内置预设，返回新增数量（已存在则跳过，不覆盖用户改动）。"""
        defaults = self.load_voiceforge_defaults()
        if not defaults:
            return 0
        templates = self.load_json_templates()
        existing = {t.get("id") for t in templates}
        added = 0
        for item in defaults:
            if item.get("id") not in existing:
                templates.append(copy.deepcopy(item))
                added += 1
        if added:
            self.save_json_templates(templates)
        return added

    def create_json_template(self, data: dict, scope: str = "voiceforge") -> dict:
        """新建一个限定作用域的 Prompt 预设。"""
        templates = self.load_json_templates()
        template_id = str(data.get("id") or "").strip() or f"voiceforge_preset_{uuid.uuid4().hex[:8]}"
        if any(t.get("id") == template_id for t in templates):
            raise ValueError(f"预设 id 已存在：{template_id}")
        placeholders = data.get("placeholders") or []
        template = {
            "id": template_id,
            "name": str(data.get("name") or template_id).strip(),
            "description": data.get("description") or "",
            "scope": scope,
            "category": data.get("category") or "自定义",
            "placeholders": placeholders if isinstance(placeholders, list) else [],
            "system_prompt": data.get("system_prompt") or "",
            "user_prompt": data.get("user_prompt") or "",
        }
        templates.append(template)
        self.save_json_templates(templates)
        return template

    def delete_json_template(self, prompt_id: str) -> bool:
        """删除一个 Prompt 预设。返回是否命中。"""
        templates = self.load_json_templates()
        remaining = [t for t in templates if t.get("id") != prompt_id]
        if len(remaining) == len(templates):
            return False
        self.save_json_templates(remaining)
        return True

    def reset_json_template(self, prompt_id: str) -> bool:
        """把某条预设恢复为配音谷内置默认内容。返回是否命中默认库。"""
        default_item = next(
            (t for t in self.load_voiceforge_defaults() if t.get("id") == prompt_id), None
        )
        if not default_item:
            return False
        templates = self.load_json_templates()
        for i, t in enumerate(templates):
            if t.get("id") == prompt_id:
                templates[i] = copy.deepcopy(default_item)
                self.save_json_templates(templates)
                return True
        # 已被删除则重新补种
        templates.append(copy.deepcopy(default_item))
        self.save_json_templates(templates)
        return True

    def get_json_template_by_id(self, prompt_id: str) -> Optional[dict]:
        """Get a single prompt template by its ID."""
        templates = self.load_json_templates()
        for t in templates:
            if t.get("id") == prompt_id:
                return t
        return None

    def save_json_templates(self, templates: list[dict]):
        """Save the entire templates list to prompt_templates.json and refresh cache."""
        data = {"version": "1.0", "templates": templates}
        with self._json_lock:
            with open(self._json_templates_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._json_cache = templates

    def update_json_template(self, prompt_id: str, update_data: dict) -> bool:
        """Update a single template by ID. Returns True if found and updated."""
        templates = self.load_json_templates()
        for i, t in enumerate(templates):
            if t.get("id") == prompt_id:
                for key in ("name", "description", "category", "placeholders", "system_prompt", "user_prompt"):
                    if key in update_data:
                        templates[i][key] = update_data[key]
                self.save_json_templates(templates)
                return True
        return False

    def assemble_prompt(self, prompt_id: str, placeholder_data: dict) -> dict:
        """
        Assemble a complete prompt from template ID and placeholder data using Jinja2.

        Args:
            prompt_id: Template identifier (e.g. "s04_summarize")
            placeholder_data: Dict of placeholder values to inject
        """
        template_data = self.get_json_template_by_id(prompt_id)
        if not template_data:
            return {"system_prompt": "", "user_prompt": "", "found": False}

        system_tpl_str = template_data.get("system_prompt", "")
        user_tpl_str = template_data.get("user_prompt", "")

        try:
            # Render with Jinja2
            system_tpl = self.jinja_env.from_string(system_tpl_str)
            user_tpl = self.jinja_env.from_string(user_tpl_str)
            
            system_prompt = system_tpl.render(**placeholder_data)
            user_prompt = user_tpl.render(**placeholder_data)
            
            return {"system_prompt": system_prompt, "user_prompt": user_prompt, "found": True}
        except Exception as e:
            # Fallback to simple replace if Jinja2 fails
            system_prompt = system_tpl_str
            user_prompt = user_tpl_str
            for tag, value in placeholder_data.items():
                # Try both {tag} and {{tag}}
                for pattern in ["{" + tag + "}", "{{" + tag + "}}"]:
                    str_value = str(value) if value is not None else ""
                    system_prompt = system_prompt.replace(pattern, str_value)
                    user_prompt = user_prompt.replace(pattern, str_value)
            return {"system_prompt": system_prompt, "user_prompt": user_prompt, "found": True}

    def extract_placeholders(self, text: str) -> Set[str]:
        """Extract all variables from Jinja2 template text."""
        try:
            ast = self.jinja_env.parse(text)
            return meta.find_undeclared_variables(ast)
        except Exception:
            # Fallback to regex for {tag}
            tags = re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', text)
            return set(tags)

    def validate_placeholders(self, prompt_id: str, system_prompt: str, user_prompt: str) -> dict:
        """
        Validate placeholder usage in edited prompts against the template's defined placeholders.
        """
        template = self.get_json_template_by_id(prompt_id)
        if not template:
            return {"invalid": [], "unused": [], "valid": True}

        # Defined tags are simple names (no braces)
        defined_tags = {p["tag"].strip("{}") for p in template.get("placeholders", [])}
        
        used_in_system = self.extract_placeholders(system_prompt)
        used_in_user = self.extract_placeholders(user_prompt)
        all_used = used_in_system | used_in_user

        invalid = []
        for tag in sorted(all_used - defined_tags):
            location = []
            if tag in used_in_system:
                location.append("system_prompt")
            if tag in used_in_user:
                location.append("user_prompt")
            invalid.append({"tag": tag, "location": ", ".join(location)})

        unused = sorted(defined_tags - all_used)

        return {
            "invalid": invalid,
            "unused": unused,
            "valid": len(invalid) == 0 and len(unused) == 0,
        }


# Singleton
_service: Optional[PromptService] = None


def get_prompt_service() -> PromptService:
    global _service
    if _service is None:
        _service = PromptService()
    return _service
