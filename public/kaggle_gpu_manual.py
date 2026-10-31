import asyncio
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.request

# Replace this with a long random secret. Paste the same value into
# Settings > Kaggle GPU in THE AFTERLIFE. No Kaggle API token is needed.
GATEWAY_TOKEN = "REPLACE_WITH_A_LONG_RANDOM_SECRET_32_CHARS_OR_MORE"
if len(GATEWAY_TOKEN) < 24 or GATEWAY_TOKEN.startswith("REPLACE_"):
    raise ValueError("Set GATEWAY_TOKEN to a private random value of at least 24 characters.")

subprocess.run(["pip", "-q", "install", "fastapi", "uvicorn", "httpx"], check=True)
os.makedirs("/kaggle/working", exist_ok=True)

gateway_source = r'''
from collections import defaultdict, deque
import os, time, httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TOKEN = os.environ["AFTERLIFE_GATEWAY_TOKEN"]
UPSTREAM = "http://127.0.0.1:11434"
hits = defaultdict(deque)

def auth(value):
    if value != "Bearer " + TOKEN:
        raise HTTPException(401, "Unauthorized")

@app.get("/health")
async def health(authorization: str | None = Header(default=None)):
    auth(authorization)
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(UPSTREAM + "/api/tags")
        response.raise_for_status()
    return {"status": "ok"}

@app.get("/api/tags")
async def tags(authorization: str | None = Header(default=None)):
    auth(authorization)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(UPSTREAM + "/api/tags")
        response.raise_for_status()
        return response.json()

@app.post("/api/{route:path}")
async def inference(route: str, request: Request, authorization: str | None = Header(default=None)):
    auth(authorization)
    path = "/api/" + route
    if path not in ("/api/chat", "/api/generate"):
        raise HTTPException(404, "Route not allowed")
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    now = time.time()
    recent = hits[ip]
    while recent and recent[0] < now - 60:
        recent.popleft()
    if len(recent) >= 30:
        raise HTTPException(429, "Rate limited")
    recent.append(now)
    payload = await request.json()
    if len(str(payload)) > 1_000_000:
        raise HTTPException(413, "Request too large")
    if payload.get("stream"):
        async def chunks():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", UPSTREAM + path, json=payload) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk
        return StreamingResponse(chunks(), media_type="application/x-ndjson")
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(UPSTREAM + path, json=payload)
        response.raise_for_status()
        return response.json()
'''
with open("/kaggle/working/afterlife_gateway.py", "w") as file:
    file.write(gateway_source)

import torch
if not torch.cuda.is_available():
    raise RuntimeError("Turn on GPU in Notebook settings, then run this cell again.")
vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
gpu_name = torch.cuda.get_device_name(0)
model = "gemma3:4b" if vram_gb < 16 else ("gemma3:12b" if vram_gb < 32 else "gemma3:27b")
print(f"GPU: {gpu_name} · {vram_gb:.1f} GB · Model: {model}")

subprocess.run("apt-get install -y zstd >/dev/null 2>&1 || true", shell=True)
subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True)
ollama = subprocess.Popen(["ollama", "serve"], env=dict(os.environ, OLLAMA_HOST="127.0.0.1:11434"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(45):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError("Ollama did not start. Restart the Kaggle session and run this cell again.")

subprocess.run(["ollama", "pull", model], check=True)
env = dict(os.environ, AFTERLIFE_GATEWAY_TOKEN=GATEWAY_TOKEN)
gateway_log = open("/kaggle/working/afterlife-gateway.log", "w")
gateway = subprocess.Popen(["uvicorn", "afterlife_gateway:app", "--host", "127.0.0.1", "--port", "8787"], cwd="/kaggle/working", env=env, stdout=gateway_log, stderr=subprocess.STDOUT)
time.sleep(3)
if gateway.poll() is not None:
    raise RuntimeError("Gateway failed to start. Check /kaggle/working/afterlife-gateway.log")

cloudflared = "/kaggle/working/cloudflared"
if not os.path.exists(cloudflared):
    subprocess.run(["curl", "-fsSL", "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", "-o", cloudflared], check=True)
    os.chmod(cloudflared, 0o755)
tunnel = subprocess.Popen([cloudflared, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8787"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
lines = queue.Queue()
def read_tunnel():
    for line in tunnel.stdout:
        lines.put(line)
threading.Thread(target=read_tunnel, daemon=True).start()
endpoint = None
end_at = time.time() + 90
while time.time() < end_at and tunnel.poll() is None:
    try:
        line = lines.get(timeout=1)
    except queue.Empty:
        continue
    match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
    if match:
        endpoint = match.group(0)
        break
if not endpoint:
    raise RuntimeError("Cloudflare tunnel did not start. Check Kaggle internet access and run this cell again.")

headers = {"Authorization": "Bearer " + GATEWAY_TOKEN}
for _ in range(30):
    try:
        urllib.request.urlopen(urllib.request.Request(endpoint + "/health", headers=headers), timeout=10)
        break
    except Exception:
        time.sleep(2)
else:
    raise RuntimeError("The tunnel URL did not respond. Run this cell again.")

print("\nConnection details for THE AFTERLIFE Settings")
print("Gateway URL:", endpoint)
print("Gateway token: the value of GATEWAY_TOKEN above")
print("Keep this Kaggle cell running while you use the app.")
await asyncio.Event().wait()
