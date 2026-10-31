from __future__ import annotations
import json
import httpx


class InferenceError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class OllamaClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 90):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def tags(self):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(f"{self.base_url}/api/tags", headers=self._headers())
                response.raise_for_status()
                return response.json().get("models", [])
        except httpx.TimeoutException as exc:
            raise InferenceError("INFERENCE_TIMEOUT", "The inference service did not respond in time.") from exc
        except httpx.HTTPStatusError as exc:
            raise InferenceError("INFERENCE_AUTH_FAILED" if exc.response.status_code in (401, 403) else "INFERENCE_UNAVAILABLE", "The inference service rejected the connection or is unavailable.") from exc
        except Exception as exc:
            raise InferenceError("INFERENCE_UNAVAILABLE", "The inference service is unavailable.") from exc

    async def generate_json(self, model: str, prompt: str):
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/generate", headers=self._headers(), json={"model": model, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0.25}})
                response.raise_for_status()
                text=response.json().get("response", "")
        except Exception as exc:
            raise InferenceError("GENERATION_FAILED", "The archive could not prepare this voice. Try again later.") from exc
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Ollama returned invalid JSON") from exc

    async def pull(self, model: str):
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST",f"{self.base_url}/api/pull",headers=self._headers(),json={"name":model,"stream":True}) as response:
                    if response.status_code in (401,403): raise InferenceError("INFERENCE_AUTH_FAILED","The inference service rejected the connection.")
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            try: yield json.loads(line)
                            except json.JSONDecodeError: continue
        except InferenceError: raise
        except Exception as exc: raise InferenceError("MODEL_DOWNLOAD_FAILED","The model could not be downloaded. Check the connection and retry.") from exc

    async def chat(self, model: str, messages: list[dict]):
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", headers=self._headers(), json={"model": model, "messages": messages, "stream": True, "options": {"num_predict": 192, "stop": ["\n\n---"]}}) as response:
                    if response.status_code in (401, 403):
                        raise InferenceError("INFERENCE_AUTH_FAILED", "The inference service rejected the connection.")
                    if response.status_code >= 400:
                        raise InferenceError("INFERENCE_UNAVAILABLE", "The inference service is unavailable.")
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if chunk.get("done"):
                                return
                        except json.JSONDecodeError:
                            continue
        except InferenceError:
            raise
        except httpx.TimeoutException as exc:
            raise InferenceError("INFERENCE_TIMEOUT", "The inference service did not respond in time.") from exc
        except Exception as exc:
            raise InferenceError("INFERENCE_UNAVAILABLE", "The inference service is unavailable.") from exc
