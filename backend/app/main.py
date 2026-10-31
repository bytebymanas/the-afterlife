from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import router
from .config import settings
from .database import SessionLocal, ensure_runtime_schema
from .services import seed_predefined


@asynccontextmanager
async def lifespan(app):
    ensure_runtime_schema()
    with SessionLocal() as db: seed_predefined(db)
    yield

app=FastAPI(title="THE AFTERLIFE API",version="0.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=False,allow_methods=["GET","POST","PUT"],allow_headers=["Content-Type","Idempotency-Key"])
app.include_router(router)

@app.get("/")
def root(): return {"service":"THE AFTERLIFE API","docs":"/docs"}
