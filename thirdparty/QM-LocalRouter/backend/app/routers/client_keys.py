"""Client (virtual) key management + outbound endpoint registry."""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client_key import ClientKey
from app.routers.settings import _get_settings
from app.services.access_auth import ENDPOINT_GROUPS

router = APIRouter(prefix="/api/client-keys", tags=["client-keys"])
endpoints_router = APIRouter(prefix="/api", tags=["endpoints"])

ENDPOINT_DESCRIPTIONS = {
    # (group, method, path): (zh, en)
    ("openai", "POST", "/v1/chat/completions"): ("OpenAI 兼容对话（核心端点，按策略名或直连模型路由）", "OpenAI-compatible chat completions (core)"),
    ("openai", "POST", "/v1/completions"): ("OpenAI 兼容文本补全（旧版接口）", "OpenAI-compatible text completions (legacy)"),
    ("openai", "GET", "/v1/models"): ("模型目录：返回所有启用中的策略（作为模型名使用）", "Model catalog: lists active strategies (usable as model names)"),
    ("openai", "POST", "/v1/embeddings"): ("文本向量化（openai/gemini 协议）", "Text embeddings (openai/gemini protocols)"),
    ("media", "POST", "/v1/audio/transcriptions"): ("音频转文字（Whisper 类模型，multipart 上传）", "Audio transcription (Whisper-style models, multipart upload)"),
    ("media", "POST", "/v1/images/generations"): ("图像生成", "Image generation"),
    ("media", "POST", "/v1/audio/speech"): ("语音合成（TTS）", "Text-to-speech"),
    ("media", "POST", "/v1/videos"): ("视频生成任务", "Video generation task"),
    ("media", "GET", "/v1/videos/{task_id}"): ("查询视频生成任务状态", "Query video task status"),
    ("multi", "POST", "/v1/multi/chat/completions"): ("多模型并发对话（聚合多个策略/模型结果）", "Multi-model concurrent chat (aggregated)"),
    ("multi", "POST", "/v1/multi/stream/chat/completions"): ("多模型并发流式对话", "Multi-model concurrent streaming chat"),
    ("alias", "POST", "/k/{client_key}/v1/chat/completions"): ("Key 内嵌路径别名：供无法携带 Header 的客户端使用", "Key-in-path alias for clients that cannot send headers"),
    ("alias", "GET", "/k/{client_key}/v1/models"): ("Key 内嵌路径别名：模型目录", "Key-in-path alias: model catalog"),
}

GROUP_LABELS = {
    "openai": {"zh": "OpenAI 兼容", "en": "OpenAI compatible"},
    "media": {"zh": "多模态生成", "en": "Media generation"},
    "multi": {"zh": "多模型聚合", "en": "Multi-model"},
    "alias": {"zh": "路径别名", "en": "Path aliases"},
}


class ClientKeyCreate(BaseModel):
    name: str = ""

class ClientKeyUpdate(BaseModel):
    is_active: bool | None = None
    name: str | None = None


def _key_to_out(k: ClientKey) -> dict:
    return {
        "id": k.id,
        "name": k.name or "",
        "key_value": k.key_value,
        "key_masked": k.key_value[:8] + "****" + k.key_value[-4:] if len(k.key_value) > 12 else "****",
        "is_active": bool(k.is_active),
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
    }


@router.get("")
async def list_client_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ClientKey).order_by(ClientKey.id))
    return [_key_to_out(k) for k in result.scalars().all()]


@router.post("", status_code=201)
async def create_client_key(data: ClientKeyCreate, db: AsyncSession = Depends(get_db)):
    key = ClientKey(
        name=(data.name or "").strip()[:100],
        key_value="sk-lr-" + secrets.token_hex(20),
        is_active=True,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return _key_to_out(key)


@router.patch("/{key_id}")
async def update_client_key(key_id: int, data: ClientKeyUpdate, db: AsyncSession = Depends(get_db)):
    key = await db.get(ClientKey, key_id)
    if not key:
        raise HTTPException(404, "Client key not found")
    if data.is_active is not None:
        key.is_active = data.is_active
    if data.name is not None:
        key.name = data.name.strip()[:100]
    await db.commit()
    await db.refresh(key)
    return _key_to_out(key)


@router.delete("/{key_id}", status_code=204)
async def delete_client_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await db.get(ClientKey, key_id)
    if not key:
        raise HTTPException(404, "Client key not found")
    await db.delete(key)
    await db.commit()


@endpoints_router.get("/endpoints")
async def get_endpoints_registry():
    """Single source of truth for the exposed outbound endpoints."""
    locale_items = []
    for group, endpoints in ENDPOINT_GROUPS.items():
        for method, path in endpoints:
            zh, en = ENDPOINT_DESCRIPTIONS.get((group, method, path), ("", ""))
            locale_items.append({
                "group": group,
                "group_label": GROUP_LABELS.get(group, {}),
                "method": method,
                "path": path,
                "desc": {"zh": zh, "en": en},
            })
    settings = _get_settings()
    return {
        "auth_mode": settings.get("auth_mode", "open"),
        "enabled_groups": settings.get("enabled_groups") or {},
        "endpoints": locale_items,
    }
