"""Prompts API: list, preview, edit, and test prompt templates.
Also provides CRUD for JSON-based prompt templates (Prompt Engineering)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from backend.prompts.prompt_service import get_prompt_service

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


# ── Legacy endpoints (templates.py based) ──────────────────────────

@router.get("")
async def list_prompt_steps():
    """List all steps with prompt templates."""
    svc = get_prompt_service()
    return {"steps": svc.list_steps()}


@router.get("/languages/current")
async def get_current_languages():
    """Get current language configuration."""
    svc = get_prompt_service()
    return svc._get_languages()


# ── JSON-based Prompt Template CRUD (Prompt Engineering) ───────────

@router.get("/templates")
async def list_json_templates(scope: Optional[str] = None):
    """Get prompt templates from prompt_templates.json.

    scope 用于按功能域过滤（如 scope=voiceforge 只返回晴沐配音谷的 Prompt 预设）。
    """
    svc = get_prompt_service()
    if scope == "voiceforge":
        # 内置预设缺失时自动补种，避免用户删除后无法找回
        svc.seed_voiceforge_defaults()
    return {"templates": svc.load_json_templates(scope)}


@router.get("/templates/{prompt_id}")
async def get_json_template(prompt_id: str):
    """Get a single prompt template by ID."""
    svc = get_prompt_service()
    template = svc.get_json_template_by_id(prompt_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{prompt_id}' not found")
    return template


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    placeholders: Optional[List[dict]] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None


@router.put("/templates/{prompt_id}")
async def update_json_template(prompt_id: str, req: UpdateTemplateRequest):
    """Update a single template's editable fields."""
    svc = get_prompt_service()
    update_data = req.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "name" in update_data and not str(update_data["name"]).strip():
        raise HTTPException(status_code=400, detail="预设名称不能为空")
    found = svc.update_json_template(prompt_id, update_data)
    if not found:
        raise HTTPException(status_code=404, detail=f"Template '{prompt_id}' not found")
    return {"ok": True, "prompt_id": prompt_id}


class CreateTemplateRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    placeholders: Optional[List[dict]] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None


@router.post("/templates")
async def create_json_template(req: CreateTemplateRequest):
    """Create a Prompt preset limited to the voiceforge scope."""
    svc = get_prompt_service()
    try:
        template = svc.create_json_template(req.model_dump(exclude_none=True), scope="voiceforge")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "template": template}


@router.delete("/templates/{prompt_id}")
async def delete_json_template(prompt_id: str):
    """Delete a voiceforge-scoped Prompt preset."""
    svc = get_prompt_service()
    template = svc.get_json_template_by_id(prompt_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{prompt_id}' not found")
    if (template.get("scope") or "global") != "voiceforge":
        raise HTTPException(status_code=403, detail="只能删除晴沐配音谷的 Prompt 预设")
    svc.delete_json_template(prompt_id)
    return {"ok": True, "prompt_id": prompt_id}


@router.post("/templates/{prompt_id}/reset")
async def reset_json_template(prompt_id: str):
    """Restore a voiceforge Prompt preset to its built-in default content."""
    svc = get_prompt_service()
    if not svc.reset_json_template(prompt_id):
        raise HTTPException(status_code=404, detail=f"未找到预设 '{prompt_id}' 的内置默认内容")
    return {"ok": True, "prompt_id": prompt_id}


class ValidateRequest(BaseModel):
    system_prompt: str
    user_prompt: str


@router.post("/templates/{prompt_id}/validate")
async def validate_template_placeholders(prompt_id: str, req: ValidateRequest):
    """Validate placeholder usage in edited prompts."""
    svc = get_prompt_service()
    result = svc.validate_placeholders(prompt_id, req.system_prompt, req.user_prompt)
    return result


class AssembleRequest(BaseModel):
    prompt_id: str
    placeholder_data: dict


@router.post("/assemble")
async def assemble_prompt(req: AssembleRequest):
    """Assemble a complete prompt from template ID and placeholder data."""
    svc = get_prompt_service()
    result = svc.assemble_prompt(req.prompt_id, req.placeholder_data)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Template '{req.prompt_id}' not found")
    return result
