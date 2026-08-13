from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func
from app.database import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    protocol = Column(String(20), nullable=False, default="openai")
    base_url = Column(String(500), nullable=False)
    description = Column(Text, default="")
    icon = Column(String(500), default="")
    homepage = Column(String(500), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
