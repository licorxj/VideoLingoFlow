from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, func
from app.database import Base


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    model_id = Column(String(200), nullable=False)
    display_name = Column(String(200), default="")
    is_active = Column(Boolean, default=True)
    is_multimodal = Column(Boolean, default=False)
    model_type = Column(String(20), default="text")  # text/image/video/tts/embedding
    context_window = Column(Integer, nullable=True)
    temperature = Column(Float, nullable=True)
    price_input = Column(Float, nullable=True)   # per 1M tokens
    price_output = Column(Float, nullable=True)  # per 1M tokens
    status = Column(String(20), default="untested")  # untested/active/inactive
    last_error = Column(String(500), default="")
    created_at = Column(DateTime, server_default=func.now())
