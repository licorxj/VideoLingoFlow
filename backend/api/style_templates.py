"""风格模板 + 提示词优化接口（供工作流节点「提示词组装」弹窗使用）。

- ``GET  /api/style-templates``                    画风/视频风格模板列表（?kind=art|video）
- ``GET  /api/style-templates/optimize-templates`` 可选的提示词优化 LLM 模板
- ``GET  /api/style-templates/{kind}/{id}``        模板详情（含变量槽表单定义）
- ``POST /api/style-templates/assemble``           按模板 + 变量值渲染提示词（纯拼装，不调 LLM）
- ``POST /api/style-templates/optimize``           用所选 LLM 模板改写/扩写提示词

模板资产在 ``backend/config/style_presets/*.json``，优化模板在
``backend/config/drama_prompts/*_prompt_optimize.md``（改文件即生效）。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import style_templates as st

router = APIRouter(prefix="/api/style-templates", tags=["style-templates"])


class AssembleIn(BaseModel):
    kind: str = "art"                      # art | video
    template_id: str = ""
    values: dict = {}
    style_prefix: str = ""                 # 项目统一画风前缀（画风锁定）
    extra_suffix: str = ""                 # 追加在末尾的自由文本


class OptimizeIn(BaseModel):
    kind: str = "art"                      # art（生图）| video（视频）
    text: str = ""                         # 待优化的原始提示词
    template: str = ""                     # 优化模板 key：image|video，留空按 kind 推导
    style_hint: str = ""                   # 项目统一画风（作为约束注入）
    model: str = ""                        # 指定模型，留空走 LLM 路由


@router.get("")
def list_templates(kind: str = "art", category: str = "", keyword: str = ""):
    if kind not in ("art", "video"):
        raise HTTPException(status_code=400, detail="kind 只能是 art 或 video")
    return st.list_templates(kind, category=category, keyword=keyword)


@router.get("/optimize-templates")
def list_optimize_templates(kind: str = ""):
    """提示词优化模板列表（drama_prompts 下的 *_prompt_optimize.md）。"""
    return {"templates": st.list_optimize_templates(kind)}


@router.get("/{kind}/{template_id}")
def get_template(kind: str, template_id: str):
    tpl = st.get_template(kind, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return tpl


@router.post("/assemble")
def assemble(data: AssembleIn):
    """纯拼装：模板 + 变量值 → 最终提示词（不调用 LLM，前端可实时预览）。"""
    if not data.template_id:
        raise HTTPException(status_code=400, detail="template_id 不能为空")
    try:
        return st.render(data.kind, data.template_id, data.values or {},
                         style_prefix=data.style_prefix or "",
                         extra_suffix=data.extra_suffix or "")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/optimize")
def optimize(data: OptimizeIn):
    """用所选 LLM 模板优化提示词：模板正文做 system_prompt，原提示词做 user 输入。"""
    text = (data.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="待优化提示词不能为空")
    kind = "video" if data.kind == "video" else "art"
    tpl_key = (data.template or "").strip() or ("video" if kind == "video" else "image")
    system_prompt = st.load_optimize_system_prompt(tpl_key)
    if not system_prompt:
        raise HTTPException(status_code=404, detail=f"优化模板不存在: {tpl_key}")

    user_prompt = text
    hint = (data.style_hint or "").strip()
    if hint:
        user_prompt = f"项目统一画风（必须保持，不要改写）：{hint}\n\n待优化提示词：{text}"

    from backend.llm.llm_client import get_llm_client
    try:
        out = get_llm_client().chat(
            st.optimize_step_name(tpl_key),
            user_prompt,
            system_prompt=system_prompt,
            response_json=False,
            model_override=data.model or "",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败：{exc}") from exc

    result = out if isinstance(out, str) else _as_text(out)
    return {
        "prompt": result.strip(),
        "template": tpl_key,
        "model": data.model or "",
        "source_length": len(text),
    }


def _as_text(value) -> str:
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
