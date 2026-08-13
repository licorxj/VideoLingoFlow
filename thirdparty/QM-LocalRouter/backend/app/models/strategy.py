from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, default="")
    lb_strategy = Column(String(20), default="round_robin")
    key_strategy = Column(String(20), default="round_robin")
    key_switch_mode = Column(String(20), default="none")
    key_rpm_threshold = Column(Integer, default=0)
    key_count_threshold = Column(Integer, default=0)
    rule_token_threshold = Column(Integer, default=0)
    rule_token_period = Column(String(20), default="per_day")
    is_active = Column(Boolean, default=True)
    timeout = Column(Integer, default=120)
    retry_count = Column(Integer, default=2)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    rules = relationship("StrategyRule", backref="strategy", lazy="selectin")


class StrategyRule(Base):
    __tablename__ = "strategy_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    priority = Column(Integer, default=0)
    weight = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)

    model = relationship("Model", foreign_keys=[model_id], lazy="joined")
