from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, func
from app.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), default="New Chat")
    strategy_name = Column(String(200), default="")
    chat_mode = Column(String(20), default="strategy")  # strategy or model
    stream_mode = Column(Boolean, default=True)  # stream or non-stream
    model_used = Column(String(200), default="")  # actual model used
    provider_used = Column(String(200), default="")  # provider name
    messages = Column(Text, default="[]")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
