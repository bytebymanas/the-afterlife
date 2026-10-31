"""Lifecycle helpers for a local Ollama service on a single-user installation."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time

import httpx

from .config import settings
from .inference import InferenceError, OllamaClient

_process = None


def available_memory_gb() -> float:
    try:
        if platform.system() == "Darwin":
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=2)
            return int(raw.strip()) / (1024 ** 3)
        if platform.system() == "Linux":
            for line in open("/proc/meminfo", encoding="ascii"):
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 ** 2)
    except Exception:
        pass
    return 8.0


def recommended_local_model(memory_gb: float | None = None) -> str:
    memory_gb = memory_gb or available_memory_gb()
    if memory_gb >= 48:
        return "gemma3:27b"
    if memory_gb >= 24:
        return "gemma3:12b"
    if memory_gb >= 12:
        return "gemma3:4b"
    return "gemma3:1b"


async def ensure_ollama_running(base_url: str | None = None):
    global _process
    base_url = (base_url or settings.ollama_base_url).rstrip("/")
    async with httpx.AsyncClient(timeout=2) as client:
        try:
            response = await client.get(f"{base_url}/api/tags")
            response.raise_for_status()
            return
        except Exception:
            pass
    binary = shutil.which("ollama")
    if not binary:
        raise InferenceError("LOCAL_OLLAMA_NOT_INSTALLED", "Install Ollama to use Local Computer.")
    if _process is None or _process.poll() is not None:
        env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434")
        _process = subprocess.Popen([binary, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        await __import__("asyncio").sleep(1)
        async with httpx.AsyncClient(timeout=2) as client:
            try:
                response = await client.get(f"{base_url}/api/tags")
                response.raise_for_status()
                return
            except Exception:
                if _process.poll() is not None:
                    raise InferenceError("LOCAL_OLLAMA_START_FAILED", "Ollama could not start on this computer.")
    raise InferenceError("LOCAL_OLLAMA_START_TIMEOUT", "Ollama did not respond in time.")


async def ensure_local_model(client: OllamaClient, model: str | None = None) -> str:
    await ensure_ollama_running()
    installed = await client.tags()
    if installed:
        gemma = [item for item in installed if item.get("name", "").startswith("gemma3:")]
        if model and any(item.get("name") == model for item in installed):
            return model
        if gemma:
            return min(gemma, key=lambda item: item.get("size", 10**20)).get("name", recommended_local_model())
    model = model or recommended_local_model()
    async for _ in client.pull(model):
        pass
    return model
