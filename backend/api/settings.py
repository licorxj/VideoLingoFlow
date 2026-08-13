"""Settings API: read/write YAML config."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

from backend.config.config_manager import config

router = APIRouter()


@router.get("")
async def get_settings():
    return {"config": config.get_all()}


@router.get("/{key:path}")
async def get_setting(key: str):
    value = config.get(key)
    if value is None:
        return {"key": key, "value": None, "exists": False}
    return {"key": key, "value": value, "exists": True}


class UpdateSettingRequest(BaseModel):
    key: str
    value: Any


@router.put("")
async def update_setting(req: UpdateSettingRequest):
    config.set(req.key, req.value)
    return {"success": True, "key": req.key, "value": config.get(req.key)}
