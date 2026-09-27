from sqlalchemy import Column, Integer, String, DateTime, func
from app.database import Base


class RotationState(Base):
    """Persisted round-robin counters so rotation continues across restarts.

    scope examples: "rule_{strategy_id}" for rule rotation, "key_{provider_id}" for key rotation.
    rr_index stores the raw selection counter; the picked slot is rr_index % len(candidates).
    """
    __tablename__ = "rotation_states"

    scope = Column(String(100), primary_key=True)
    rr_index = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
