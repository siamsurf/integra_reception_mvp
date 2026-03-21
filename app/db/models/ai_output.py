from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AIOutput(Base):
    __tablename__ = "ai_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    classification: Mapped[str] = mapped_column(String(64))
    manager_summary: Mapped[str] = mapped_column(Text)
    draft_reply: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(100))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    lead = relationship("Lead", back_populates="ai_outputs")
