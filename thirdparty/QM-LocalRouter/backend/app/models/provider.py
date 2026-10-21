from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func
from app.database import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    protocol = Column(String(20), nullable=False, default="openai")
    base_url = Column(String(500), nullable=False)
    auth_type = Column(String(20), default="api_key")  # api_key / oauth profile id
    # 直连模式（model = "平台id/模型id"）下的多 Key 调用策略；
    # 策略链路仍以 Strategy 的 key_* 设置为准
    key_strategy = Column(String(20), default="round_robin")     # round_robin / random / failover
    key_switch_mode = Column(String(20), default="none")          # none / rpm_threshold / count_threshold
    key_rpm_threshold = Column(Integer, default=0)
    key_count_threshold = Column(Integer, default=0)
    description = Column(Text, default="")
    icon = Column(String(500), default="")
    homepage = Column(String(500), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
