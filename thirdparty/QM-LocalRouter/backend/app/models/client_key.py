from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from app.database import Base


class ClientKey(Base):
    """Virtual keys issued by this router for inbound client authentication."""
    __tablename__ = "client_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), default="")
    key_value = Column(String(120), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    last_used_at = Column(DateTime, nullable=True)
