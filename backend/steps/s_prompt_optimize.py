# -*- coding: utf-8 -*-
"""提示词优化节点（生图 / 生视频）。

两个节点行为一致，只有「优化模板」与「风格模板类型」不同：

1. 原始提示词取值优先级：**输入端口 text**（可接文本节点，值为文本或文本文件路径）
   > **节点面板「自定义原始提示词」**
2. 面板「提示词组装」按钮打开风格/提示词组装弹窗，选模板填槽后写回
   ``style_template_id`` 与 ``assemble_result``（风格段 + 画面要求）
3. 执行时把「风格段 + 原始提示词」拼成用户消息，以
   ``backend/config/drama_prompts/*_prompt_optimize.md`` 作为 system_prompt 调 LLM
4. LLM 返回优化后的提示词 → 落盘 ``<task_dir>/cache/<base>_<node_id>.txt``
   → 输出 ``text``（优化后提示词全文）与 ``file_path``（落盘绝对路径）
"""
import os

from backend.config import style_templates as st
from backend.llm.llm_client import get_llm_client
from backend.steps.base_step import BaseStep

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _as_text(value, task_dir: str = "") -> str:
    """把输入值规整为文本：可直接是文本，也可以是文本文件路径（绝对 / 相对 task_dir / data/ 开头）。"""
    v = str(value or "").strip()
    if not v:
        return ""
    candidates = [v]
    if not os.path.isabs(v):
        if task_dir:
            candidates.append(os.path.join(task_dir, v))
        candidates.append(os.path.join(_PROJECT_ROOT, v))
    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:  # noqa: BLE001
                return v
    return v


def _first(value) -> str:
    """输入端口可能给 list（多连线），取第一个非空。"""
    if isinstance(value, (list, tuple)):
        for item in value:
            if str(item or "").strip():
                return str(item)
        return ""
    return str(value or "")


class _PromptOptimizeBase(BaseStep):
    """生图 / 生视频提示词优化的共同实现。"""

    dependencies = []
    #: 优化模板 key（对应 drama_prompts 的 image / video）
    opt_kind = "image"
    #: 风格模板类型（art / video）
    style_kind = "art"
    #: 落盘文件基名
    base_name = "prompt_opt_image"

    # ------------------------------------------------------------------ #
    def _out_name(self, node_id: str) -> str:
        return f"{self.base_name}_{node_id}.txt" if node_id else f"{self.base_name}.txt"

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        return os.path.isfile(os.path.join(task_dir, "cache", self._out_name(node_id)))

    def validate_inputs(self, task_dir: str) -> bool:
        """原始提示词来源之一非空即可（端口值可能是文本或文件路径，此处不展开读）。"""
        inputs = getattr(self, "_step_inputs", {}) or {}
        if str(_first(inputs.get("text")) or "").strip():
            return True
        cfg = getattr(self, "_node_config", {}) or {}
        return bool(str(cfg.get("custom_prompt") or "").strip())

    # ------------------------------------------------------------------ #
    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        node_id = getattr(self, "_node_id", "")
        cfg = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1) 原始提示词：输入端口优先，其次面板自定义输入
        raw = _as_text(_first(inputs.get("text")), task_dir)
        source = "输入端口"
        if not raw:
            raw = str(cfg.get("custom_prompt") or "").strip()
            source = "节点自定义提示词"
        if not raw:
            raise ValueError(
                "提示词优化失败：未提供原始提示词（连线输入端口 text 或填写「自定义原始提示词」）")

        if callback:
            callback(10, f"取到原始提示词（{source}），长度 {len(raw)} 字")

        # 2) 风格段：优先用弹窗组装结果；只有模板 id 时按模板现场渲染
        style_text = str(cfg.get("assemble_result") or "").strip()
        if not style_text:
            tpl_id = str(cfg.get("style_template_id") or "").strip()
            if tpl_id:
                try:
                    style_text = st.render(self.style_kind, tpl_id, {}).get("prompt") or ""
                except Exception:  # noqa: BLE001
                    style_text = ""

        # 3) 优化模板（system_prompt）
        tpl_key = str(cfg.get("opt_template") or "").strip() or self.opt_kind
        system_prompt = st.load_optimize_system_prompt(tpl_key)
        if not system_prompt:
            system_prompt = st.load_optimize_system_prompt(self.opt_kind)
        if not system_prompt:
            raise ValueError(
                f"提示词优化失败：优化模板缺失（{tpl_key}），请检查 "
                f"backend/config/drama_prompts/{self.opt_kind}_prompt_optimize.md")

        # 4) 组装 LLM 请求：风格 + 原始提示词（模板本身在 system_prompt）
        if style_text:
            user_prompt = f"风格与画面要求（必须遵守，不要改写风格本身）：{style_text}\n\n待优化提示词：{raw}"
        else:
            user_prompt = f"待优化提示词：{raw}"

        if callback:
            callback(30, f"调用 LLM 优化（模板：{tpl_key}）...")

        model = str(cfg.get("llm_model") or "").strip()
        result = get_llm_client().chat(
            step_name=self.step_id,
            prompt=user_prompt,
            system_prompt=system_prompt,
            response_json=False,
            model_override=model,
        )
        optimized = result if isinstance(result, str) else _stringify(result)
        optimized = (optimized or "").strip()
        if not optimized:
            raise ValueError("提示词优化失败：LLM 返回为空")

        # 5) 落盘
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out_name = self._out_name(node_id)
        out_path = os.path.join(cache_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(optimized)

        self.artifacts = [os.path.join("cache", out_name)]
        if callback:
            callback(100, f"提示词优化完成：{len(optimized)} 字 → {out_name}")
        return {
            "artifacts": self.artifacts,
            "outputs": {"text": optimized, "file_path": out_path},
        }


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("content", "text", "result", "output"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
    try:
        import json
        return json.dumps(value, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(value)


class S_PromptOptImage(_PromptOptimizeBase):
    """生图提示词优化：静态画面维度补全（不写运动/运镜）。"""

    step_id = "prompt_opt_image"
    step_name = "生图提示词优化"
    opt_kind = "image"
    style_kind = "art"
    base_name = "prompt_opt_image"


class S_PromptOptVideo(_PromptOptimizeBase):
    """生视频提示词优化：补全运动、运镜、景别与镜头状态。"""

    step_id = "prompt_opt_video"
    step_name = "生视频提示词优化"
    opt_kind = "video"
    style_kind = "video"
    base_name = "prompt_opt_video"
