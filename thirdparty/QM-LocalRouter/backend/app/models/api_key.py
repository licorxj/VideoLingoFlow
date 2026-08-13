from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    key_value = Column(String(500), nullable=False)  # Encrypted
    alias = Column(String(100), default="")
    status = Column(String(20), default="active")  # active/inactive/expired/rate_limited
    weight = Column(Integer, default=1)
    last_used_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
