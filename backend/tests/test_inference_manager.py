import asyncio

import pytest

from app.inference import InferenceError
from app.inference_manager import InferenceManager


class Provider:
    def __init__(self, name, tokens=(), failure=None):
        self.name = name
        self.tokens = tokens
        self.failure = failure

    async def chat(self, model, messages):
        for token in self.tokens:
            yield token
        if self.failure:
            raise self.failure


def test_manager_falls_back_before_emitting_selected_provider_content():
    remote = Provider("kaggle", failure=InferenceError("DOWN", "down"))
    local = Provider("local", tokens=["answer"])
    manager = InferenceManager(remote, local=local, fallback_enabled=True, local_model="small")

    async def collect():
        return [token async for token in manager.chat("large", [{"role": "user", "content": "hi"}])]
    tokens = asyncio.run(collect())

    assert tokens == ["answer"]
    assert manager.last_provider == "local"


def test_manager_does_not_fallback_after_partial_answer():
    remote = Provider("kaggle", tokens=["partial"], failure=InferenceError("DOWN", "down"))
    local = Provider("local", tokens=["duplicate"])
    manager = InferenceManager(remote, local=local, fallback_enabled=True, local_model="small")

    async def consume():
        stream = manager.chat("large", [])
        assert await stream.__anext__() == "partial"
        with pytest.raises(InferenceError):
            await stream.__anext__()
    asyncio.run(consume())
    assert manager.last_provider == "kaggle"
