import json
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.provider import Provider
from app.schemas.schemas import ProviderCreate, ProviderUpdate, ProviderOut
from app.services.provider_registry import (
    get_all_providers, get_provider_info, get_providers_by_protocol, search_providers
)

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("", response_model=list[ProviderOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Provider).order_by(Provider.id))
    return result.scalars().all()


@router.get("/hot-providers")
async def get_hot_providers():
    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "hot_providers.json")
    if not os.path.exists(json_path):
        return []
    with open(json_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


@router.post("", response_model=ProviderOut, status_code=201)
async def create_provider(data: ProviderCreate, db: AsyncSession = Depends(get_db)):
    provider = Provider(**data.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.get("/{provider_id}", response_model=ProviderOut)
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    return provider


@router.put("/{provider_id}", response_model=ProviderOut)
async def update_provider(provider_id: int, data: ProviderUpdate, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(provider, k, v)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    await db.delete(provider)
    await db.commit()


@router.get("/supported")
async def get_supported_providers(
    protocol: str = Query(None, description="按协议筛选: openai, azure, anthropic, gemini, ollama, custom"),
    search: str = Query(None, description="搜索关键词"),
):
    """
    获取 LiteLLM 支持的所有提供商列表

    - **protocol**: 可选，按协议类型筛选
    - **search**: 可选，搜索提供商名称
    """
    if search:
        providers = search_providers(search)
    elif protocol:
        providers = get_providers_by_protocol(protocol)
    else:
        providers = get_all_providers()

    # 转换为列表格式
    return [
        {
            "id": info.id,
            "name": info.name,
            "protocol": info.protocol,
            "icon": info.icon,
            "color": info.color,
            "docs_url": info.docs_url,
            "api_key_env": info.api_key_env,
            "base_url_hint": info.base_url_hint,
            "supports_streaming": info.supports_streaming,
            "supports_functions": info.supports_functions,
            "supports_vision": info.supports_vision,
            "supports_json_mode": info.supports_json_mode,
            "region_required": info.region_required,
            "auth_type": info.auth_type,
        }
        for info in providers.values()
    ]


@router.get("/supported/{provider_id}")
async def get_provider_details(provider_id: str):
    """获取单个支持提供商的详细信息"""
    info = get_provider_info(provider_id)
    if not info:
        raise HTTPException(404, f"Provider '{provider_id}' not supported")
    return {
        "id": info.id,
        "name": info.name,
        "protocol": info.protocol,
        "icon": info.icon,
        "color": info.color,
        "docs_url": info.docs_url,
        "api_key_env": info.api_key_env,
        "base_url_hint": info.base_url_hint,
        "supports_streaming": info.supports_streaming,
        "supports_functions": info.supports_functions,
        "supports_vision": info.supports_vision,
        "supports_json_mode": info.supports_json_mode,
        "region_required": info.region_required,
        "auth_type": info.auth_type,
    }


@router.get("/hot-providers")
async def get_hot_providers():
    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "hot_providers.json")
    if not os.path.exists(json_path):
        return []
    with open(json_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)
