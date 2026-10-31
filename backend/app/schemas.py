from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, HttpUrl


class SoulOut(BaseModel):
    id: str; name: str; canonical_name: str; aliases: list[str]; soul_type: str; identity_type: str
    life_status: str; profession: str; biography: str; character_prompt: str; active: bool
    class Config: from_attributes = True


class EvidenceOut(BaseModel):
    source_name: str; source_url: str; source_title: str; evidence_summary: str
    reported_death_date: Optional[str] = None; retrieved_at: datetime; source_quality: str
    class Config: from_attributes = True


class SummonRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    idempotency_key: Optional[str] = Field(default=None, max_length=120)
    clarification: Optional[str] = Field(default=None, max_length=240)


class ConversationCreate(BaseModel):
    soul_id: str


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    response_style: Literal["natural", "concise", "detailed"] = "natural"


class ConnectionUpdate(BaseModel):
    mode: str = Field(pattern="^(local|kaggle)$")
    endpoint: Optional[str] = Field(default=None, max_length=500)
    selected_model: Optional[str] = Field(default=None, max_length=180)
    generation_model: Optional[str] = Field(default=None, max_length=180)
    fallback_enabled: bool = False


class ConnectionOut(BaseModel):
    mode: str; endpoint: str; selected_model: str; generation_model: str
    fallback_enabled: bool; status: str


class ManualKaggleConnection(BaseModel):
    endpoint: str = Field(min_length=12, max_length=500)
    gateway_token: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=180)
    fallback_enabled: bool = True


class LocalSetupRequest(BaseModel):
    model: str = Field(min_length=1, max_length=180)
