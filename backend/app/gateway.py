"""Small gateway to expose through ngrok instead of Ollama's unauthenticated port."""
import os
import time
from collections import defaultdict, deque
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx

TOKEN=os.environ.get("AFTERLIFE_GATEWAY_TOKEN", "")
OLLAMA_URL=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
app=FastAPI(title="Afterlife protected inference gateway",docs_url=None,redoc_url=None,openapi_url=None)
events=defaultdict(deque)
ALLOWED={"/api/tags","/api/chat","/api/generate"}

def authorize(authorization: str | None):
    if not TOKEN or authorization != f"Bearer {TOKEN}": raise HTTPException(401,"Unauthorized")

@app.get("/api/tags")
async def tags(authorization: str | None=Header(default=None)):
    authorize(authorization)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response=await client.get(OLLAMA_URL+"/api/tags");response.raise_for_status();return response.json()
    except Exception: raise HTTPException(503,"Inference service unavailable")

@app.get("/health")
async def health(authorization: str | None=Header(default=None)):
    authorize(authorization)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response=await client.get(OLLAMA_URL+"/api/tags");response.raise_for_status()
        return {"status":"ok"}
    except Exception: raise HTTPException(503,"Inference service unavailable")

@app.post("/api/{route:path}")
async def inference(route: str, request: Request, authorization: str | None=Header(default=None)):
    authorize(authorization)
    path="/api/"+route
    if path not in ALLOWED: raise HTTPException(404,"Route not allowed")
    peer=request.client.host if request.client else "unknown"
    now=time.time(); window=events[peer]
    while window and window[0]<now-60:window.popleft()
    if len(window)>=30:raise HTTPException(429,"Rate limit exceeded")
    window.append(now)
    raw=await request.body()
    if len(raw)>1_000_000:raise HTTPException(413,"Request too large")
    try:
        payload=await request.json()
        if payload.get("stream") is True:
            async def chunks():
                async with httpx.AsyncClient(timeout=180) as client:
                    async with client.stream("POST",OLLAMA_URL+path,json=payload) as upstream:
                        if upstream.status_code>=400: return
                        async for chunk in upstream.aiter_bytes(): yield chunk
            return StreamingResponse(chunks(),media_type="application/x-ndjson")
        async with httpx.AsyncClient(timeout=180) as client:
            response=await client.post(OLLAMA_URL+path,json=payload);response.raise_for_status();return response.json()
    except httpx.HTTPStatusError as exc: raise HTTPException(exc.response.status_code,"Inference request failed")
    except Exception: raise HTTPException(503,"Inference service unavailable")
