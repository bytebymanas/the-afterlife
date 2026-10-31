"""Provider-independent inference routing for the application layer.

Providers implement the same small contract. Chat, souls, and summoning depend on
this manager rather than importing a provider SDK or knowing endpoint details.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from .inference import InferenceError, OllamaClient


class UnavailableProvider:
    """Stand-in used while a remote endpoint is not paired yet."""
    name = "kaggle"

    async def tags(self):
        raise InferenceError("INFERENCE_UNAVAILABLE", "The Kaggle notebook is not connected.")

    async def chat(self, model: str, messages: list[dict]):
        raise InferenceError("INFERENCE_UNAVAILABLE", "The Kaggle notebook is not connected.")
        yield ""

    async def generate_json(self, model: str, prompt: str):
        raise InferenceError("INFERENCE_UNAVAILABLE", "The Kaggle notebook is not connected.")

    def pull(self, model: str):
        async def unavailable():
            raise InferenceError("INFERENCE_UNAVAILABLE", "The Kaggle notebook is not connected.")
            yield {}
        return unavailable()


class InferenceProvider(Protocol):
    name: str

    async def tags(self) -> list[dict]: ...
    async def chat(self, model: str, messages: list[dict]) -> AsyncIterator[str]: ...
    async def generate_json(self, model: str, prompt: str) -> dict: ...
    def pull(self, model: str): ...


class OllamaProvider:
    """Ollama adapter. The Ollama URL is backend configuration, never frontend API."""

    def __init__(self, base_url: str, api_key: str | None = None, name: str = "ollama"):
        self.name = name
        self.client = OllamaClient(base_url, api_key)

    async def tags(self):
        return await self.client.tags()

    async def chat(self, model: str, messages: list[dict]):
        async for token in self.client.chat(model, messages):
            yield token

    async def generate_json(self, model: str, prompt: str):
        return await self.client.generate_json(model, prompt)

    def pull(self, model: str):
        return self.client.pull(model)


class InferenceManager:
    """Routes requests to the selected provider and applies explicit fallback."""

    def __init__(self, selected: InferenceProvider, *, local: InferenceProvider | None = None,
                 fallback_enabled: bool = False, local_model: str = ""):
        self.selected = selected
        self.local = local
        self.fallback_enabled = fallback_enabled
        self.local_model = local_model
        self.last_provider = selected.name

    async def _fallback_model(self):
        if self.local_model:
            return self.local_model
        if not self.local:
            return ""
        models = await self.local.tags()
        models = sorted(models, key=lambda item: item.get("size", 10**30))
        self.local_model = models[0].get("name", "") if models else ""
        return self.local_model

    async def tags(self):
        try:
            self.last_provider = self.selected.name
            return await self.selected.tags()
        except InferenceError:
            if not self.fallback_enabled or not self.local or self.selected.name == "local":
                raise
            models = await self.local.tags()
            self.last_provider = self.local.name
            return models

    async def generate_json(self, model: str, prompt: str):
        try:
            return await self.selected.generate_json(model, prompt)
        except InferenceError:
            if not self.fallback_enabled or not self.local or self.selected.name == "local":
                raise
            fallback_model = await self._fallback_model()
            if not fallback_model:
                raise
            self.last_provider = self.local.name
            return await self.local.generate_json(fallback_model, prompt)

    def pull(self, model: str):
        return self.selected.pull(model)

    async def chat(self, model: str, messages: list[dict]):
        self.last_provider = self.selected.name
        emitted = False
        try:
            async for token in self.selected.chat(model, messages):
                emitted = True
                yield token
        except InferenceError:
            # Never switch after content was emitted; doing so could duplicate or
            # reorder a partial answer. The caller preserves that user's turn.
            if emitted or not self.fallback_enabled or not self.local or self.selected.name == "local":
                raise
            fallback_model = await self._fallback_model()
            if not fallback_model:
                raise
            self.last_provider = self.local.name
            async for token in self.local.chat(fallback_model, messages):
                yield token
