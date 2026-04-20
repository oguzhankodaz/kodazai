from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Workflow(Base):
    __tablename__ = "workflows"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class RegistryEntry(Base):
    __tablename__ = "registry_entries"

    code: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("workflows.code", ondelete="CASCADE"),
        primary_key=True,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False)
    strict: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class QuestionLog(Base):
    """Soru havuzu / analiz: konuşma başlangıcı ve akıştaki her soru metni."""

    __tablename__ = "question_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workflow_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # user_opening | bot_question | user_answer
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
