from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def now_utc():
    return datetime.now(timezone.utc)


class Soul(Base):
    __tablename__ = "souls"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(180), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    soul_type: Mapped[str] = mapped_column(String(24), default="predefined", index=True)
    identity_type: Mapped[str] = mapped_column(String(32), default="public_figure")
    life_status: Mapped[str] = mapped_column(String(20), default="DECEASED")
    profession: Mapped[str] = mapped_column(String(180), default="")
    biography: Mapped[str] = mapped_column(Text, default="")
    character_prompt: Mapped[str] = mapped_column(Text, default="")
    personality_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    verification_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    evidence: Mapped[list["VerificationEvidence"]] = relationship(back_populates="soul", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="soul")


class SummonJob(Base):
    __tablename__ = "summon_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="REQUESTED", index=True)
    verification_result: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    confidence: Mapped[str] = mapped_column(String(20), default="insufficient")
    error_code: Mapped[Optional[str]] = mapped_column(String(48))
    generated_soul_id: Mapped[Optional[str]] = mapped_column(ForeignKey("souls.id"))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class VerificationEvidence(Base):
    __tablename__ = "verification_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    soul_id: Mapped[Optional[str]] = mapped_column(ForeignKey("souls.id"))
    summon_job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("summon_jobs.id"))
    source_name: Mapped[str] = mapped_column(String(180), default="")
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(400), default="")
    evidence_summary: Mapped[str] = mapped_column(Text, default="")
    reported_death_date: Mapped[Optional[str]] = mapped_column(String(40))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    source_quality: Mapped[str] = mapped_column(String(24), default="unknown")
    soul: Mapped[Optional[Soul]] = relationship(back_populates="evidence")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    soul_id: Mapped[str] = mapped_column(ForeignKey("souls.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    soul: Mapped[Soul] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120))
    model_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    __table_args__ = (UniqueConstraint("conversation_id", "idempotency_key", name="uq_message_idempotency"),)


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_type: Mapped[str] = mapped_column(String(24), default="local")
    connection_status: Mapped[str] = mapped_column(String(24), default="unknown")
    endpoint_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    selected_model: Mapped[str] = mapped_column(String(180), default="")
    generation_model: Mapped[str] = mapped_column(String(180), default="")
    fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


Index("ix_soul_type_canonical", Soul.soul_type, Soul.canonical_name)
