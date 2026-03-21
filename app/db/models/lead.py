from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rid: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    service_type: Mapped[str] = mapped_column(String(32), index=True)
    client_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    ai_outputs = relationship("AIOutput", back_populates="lead", cascade="all, delete-orphan")
    precheck_results = relationship("PrecheckResult", back_populates="lead", cascade="all, delete-orphan")
    attachments = relationship("Attachment", back_populates="lead", cascade="all, delete-orphan")
