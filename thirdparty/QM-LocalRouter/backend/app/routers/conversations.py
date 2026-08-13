import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.conversation import Conversation

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    strategy_name: str = ""
    chat_mode: str = "strategy"
    stream_mode: bool = True
    model_used: str = ""
    provider_used: str = ""
    messages: str = "[]"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    strategy_name: Optional[str] = None
    chat_mode: Optional[str] = None
    stream_mode: Optional[bool] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    messages: Optional[str] = None


@router.get("")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at))
    )
    items = result.scalars().all()
    return [
        {
            "id": c.id, "title": c.title, "strategy_name": c.strategy_name,
            "chat_mode": c.chat_mode, "stream_mode": c.stream_mode,
            "model_used": c.model_used, "provider_used": c.provider_used,
            "messages": c.messages,
            "created_at": str(c.created_at) if c.created_at else None,
            "updated_at": str(c.updated_at) if c.updated_at else None,
        }
        for c in items
    ]


@router.post("")
async def create_conversation(data: ConversationCreate, db: AsyncSession = Depends(get_db)):
    conv = Conversation(
        title=data.title, strategy_name=data.strategy_name,
        chat_mode=data.chat_mode, stream_mode=data.stream_mode,
        model_used=data.model_used, provider_used=data.provider_used,
        messages=data.messages
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {
        "id": conv.id, "title": conv.title, "strategy_name": conv.strategy_name,
        "chat_mode": conv.chat_mode, "stream_mode": conv.stream_mode,
        "model_used": conv.model_used, "provider_used": conv.provider_used,
        "messages": conv.messages,
        "created_at": str(conv.created_at), "updated_at": str(conv.updated_at),
    }


@router.put("/{conv_id}")
async def update_conversation(conv_id: int, data: ConversationUpdate, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if data.title is not None:
        conv.title = data.title
    if data.strategy_name is not None:
        conv.strategy_name = data.strategy_name
    if data.chat_mode is not None:
        conv.chat_mode = data.chat_mode
    if data.stream_mode is not None:
        conv.stream_mode = data.stream_mode
    if data.model_used is not None:
        conv.model_used = data.model_used
    if data.provider_used is not None:
        conv.provider_used = data.provider_used
    if data.messages is not None:
        conv.messages = data.messages
    await db.commit()
    await db.refresh(conv)
    return {
        "id": conv.id, "title": conv.title, "strategy_name": conv.strategy_name,
        "chat_mode": conv.chat_mode, "stream_mode": conv.stream_mode,
        "model_used": conv.model_used, "provider_used": conv.provider_used,
        "messages": conv.messages,
        "created_at": str(conv.created_at), "updated_at": str(conv.updated_at),
    }


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    await db.delete(conv)
    await db.commit()
    return {"ok": True}

