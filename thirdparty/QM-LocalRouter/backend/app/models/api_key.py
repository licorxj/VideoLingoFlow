from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    key_value = Column(String(500), nullable=False)  # Encrypted
    alias = Column(String(100), default="")
    status = Column(String(20), default="active")  # active/inactive/expired/rate_limited
    status_until = Column(Integer, default=0)  # 冷却截止时间(unix秒)，rate_limited 到期自动恢复
    fail_count = Column(Integer, default=0)  # 连续鉴权失败次数，达阈值才置 inactive
    weight = Column(Integer, default=1)
    oauth_profile = Column(String(50), default="")  # non-empty => token obtained via browser login
    oauth_refresh = Column(Text, default="")  # encrypted refresh token
    oauth_expires_at = Column(Integer, default=0)  # unix seconds
    last_used_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
