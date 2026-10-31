from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./afterlife.db")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_api_key: str | None = os.getenv("OLLAMA_API_KEY")
    search_provider: str = os.getenv("SEARCH_PROVIDER", "brave")
    brave_search_api_key: str | None = os.getenv("BRAVE_SEARCH_API_KEY")
    cors_origins: tuple[str, ...] = tuple(filter(None, os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")))
    conversation_model: str = os.getenv("OLLAMA_CHAT_MODEL", "")
    generation_model: str = os.getenv("OLLAMA_GENERATION_MODEL", "")
    fallback_model: str = os.getenv("OLLAMA_FALLBACK_MODEL", os.getenv("OLLAMA_CHAT_MODEL", ""))


settings = Settings()
