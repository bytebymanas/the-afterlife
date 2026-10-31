from __future__ import annotations
import json
import ipaddress
import re
import uuid
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .database import session_dependency
from .inference import InferenceError, OllamaClient
from .inference_manager import InferenceManager, OllamaProvider, UnavailableProvider
from .models import Conversation, Message, Soul, SummonJob, VerificationEvidence
from .schemas import ConnectionUpdate, ConversationCreate, ManualKaggleConnection, MessageCreate, SummonRequest
from .services import SummoningService, connection_data, seed_predefined, soul_dict

router=APIRouter(prefix="/api")

def conversation_messages(character_prompt: str, history: list[Message]):
    """Build the Ollama payload with the saved character text untouched."""
    return [{"role":"system","content":character_prompt}]+[
        {"role":m.role,"content":m.content} for m in history
    ]

def llm_for(db: Session):
    c=connection_data(db); base=c.endpoint_metadata.get("url") if c.provider_type=="kaggle" else settings.ollama_base_url
    # Kaggle endpoints must be HTTPS and use a gateway port/path, never raw Ollama's public 11434.
    if c.provider_type=="kaggle" and base:
        parsed=urlparse(base)
        host=parsed.hostname or ""
        try: private_host=ipaddress.ip_address(host).is_private
        except ValueError: private_host=host in ("localhost", "localhost.localdomain") or host.endswith(".localhost")
        if parsed.scheme!="https" or not host or private_host or parsed.port not in (None,443) or parsed.username or parsed.password:
            raise HTTPException(400,"REMOTE_ENDPOINT_INVALID")
    if c.provider_type=="local":
        key=settings.ollama_api_key
    else:
        try:
            from .secret_store import SecretStore
            key=SecretStore().get("gateway_token")
        except Exception:
            key=None
    selected=UnavailableProvider() if c.provider_type=="kaggle" and not base else OllamaProvider(base,key,name=c.provider_type)
    local=OllamaProvider(settings.ollama_base_url,settings.ollama_api_key,name="local")
    return c,InferenceManager(selected,local=local,fallback_enabled=c.fallback_enabled,local_model=settings.fallback_model)

@router.get("/health")
def health(db: Session=Depends(session_dependency)):
    try: db.execute(select(1)); return {"status":"ok","database":"ready"}
    except Exception: raise HTTPException(503,"DATABASE_UNAVAILABLE")

@router.get("/souls")
def list_souls(db: Session=Depends(session_dependency)):
    seed_predefined(db)
    return [soul_dict(s) for s in db.scalars(select(Soul).where(Soul.active.is_(True)).order_by(Soul.name))]

@router.get("/souls/{soul_id}")
def get_soul(soul_id: str, db: Session=Depends(session_dependency)):
    soul=db.get(Soul,soul_id)
    if not soul or not soul.active: raise HTTPException(404,"SOUL_NOT_FOUND")
    return soul_dict(soul)

@router.put("/souls/{soul_id}/prompt")
def update_soul_prompt(soul_id: str, body: dict, db: Session=Depends(session_dependency)):
    """Store an owner-authored character prompt verbatim for use as the system message."""
    soul=db.get(Soul,soul_id)
    if not soul or not soul.active: raise HTTPException(404,"SOUL_NOT_FOUND")
    prompt=body.get("character_prompt") if isinstance(body,dict) else None
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>12000:
        raise HTTPException(422,"CHARACTER_PROMPT_REQUIRED")
    soul.character_prompt=prompt
    db.commit()
    return {"saved":True,"soul_id":soul.id,"character_prompt":soul.character_prompt}

@router.post("/souls/summon")
async def summon(body: SummonRequest, db: Session=Depends(session_dependency)):
    seed_predefined(db)
    if not re.fullmatch(r"[\w\s.'’\-]+",body.name.strip()): raise HTTPException(422,"INVALID_NAME")
    c,llm=llm_for(db)
    svc=SummoningService(db,inference=llm,model=c.generation_model or None)
    job=await svc.summon(body.name.strip(),body.idempotency_key,body.clarification)
    evidence=db.scalars(select(VerificationEvidence).where(VerificationEvidence.summon_job_id==job.id)).all()
    return {"job_id":job.id,"requested_name":job.requested_name,"status":job.status,"verification_result":job.verification_result,"confidence":job.confidence,"error_code":job.error_code,"candidates":job.candidates or [],"soul":soul_dict(db.get(Soul,job.generated_soul_id)) if job.generated_soul_id else None,"evidence":[{"source_name":e.source_name,"source_url":e.source_url,"source_title":e.source_title,"summary":e.evidence_summary,"source_quality":e.source_quality} for e in evidence]}

@router.get("/summoning/{job_id}")
def get_summon(job_id: str, db: Session=Depends(session_dependency)):
    j=db.get(SummonJob,job_id)
    if not j: raise HTTPException(404,"SUMMON_JOB_NOT_FOUND")
    e=db.scalars(select(VerificationEvidence).where(VerificationEvidence.summon_job_id==j.id)).all()
    return {"job_id":j.id,"requested_name":j.requested_name,"status":j.status,"verification_result":j.verification_result,"error_code":j.error_code,"candidates":j.candidates or [],"soul":soul_dict(db.get(Soul,j.generated_soul_id)) if j.generated_soul_id else None,"evidence":[{"source_name":x.source_name,"source_url":x.source_url,"source_title":x.source_title,"summary":x.evidence_summary} for x in e]}

@router.post("/conversations")
def create_conversation(body: ConversationCreate, db: Session=Depends(session_dependency)):
    soul=db.get(Soul,body.soul_id)
    if not soul or not soul.active: raise HTTPException(404,"SOUL_NOT_FOUND")
    c=Conversation(id=str(uuid.uuid4()),soul_id=soul.id,title=f"Conversation with {soul.name}");db.add(c);db.commit()
    return {"id":c.id,"soul_id":c.soul_id,"title":c.title,"created_at":c.created_at}

@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, db: Session=Depends(session_dependency)):
    c=db.get(Conversation,conversation_id)
    if not c: raise HTTPException(404,"CONVERSATION_NOT_FOUND")
    return {"id":c.id,"soul_id":c.soul_id,"title":c.title,"messages":[{"role":m.role,"content":m.content,"created_at":m.created_at} for m in c.messages]}

@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, db: Session=Depends(session_dependency)):
    c=db.get(Conversation,conversation_id)
    if not c: raise HTTPException(404,"CONVERSATION_NOT_FOUND")
    return [{"role":m.role,"content":m.content,"created_at":m.created_at,"model_metadata":m.model_metadata} for m in c.messages]

@router.post("/conversations/{conversation_id}/messages")
async def chat(conversation_id: str, body: MessageCreate, db: Session=Depends(session_dependency)):
    c=db.get(Conversation,conversation_id)
    if not c: raise HTTPException(404,"CONVERSATION_NOT_FOUND")
    prior=db.scalar(select(Message).where(Message.conversation_id==c.id,Message.idempotency_key==body.idempotency_key))
    if prior: raise HTTPException(409,"MESSAGE_ALREADY_PROCESSED")
    user=Message(conversation_id=c.id,role="user",content=body.content,idempotency_key=body.idempotency_key);db.add(user);db.commit()
    history=db.scalars(select(Message).where(Message.conversation_id==c.id).order_by(Message.id)).all()
    # The manually authored soul prompt is authoritative and is passed verbatim as
    # the sole system message; UI response-style controls cannot dilute it.
    if not c.soul.character_prompt.strip():
        raise HTTPException(503,"SOUL_PROMPT_NOT_CONFIGURED")
    messages=conversation_messages(c.soul.character_prompt,history)
    conn,llm=llm_for(db); model=conn.selected_model or settings.conversation_model
    if not model: raise HTTPException(503,"MODEL_NOT_CONFIGURED")
    async def event_stream():
        result=[]
        try:
            async for token in llm.chat(model,messages):
                result.append(token); yield "data: "+json.dumps({"type":"delta","text":token},ensure_ascii=False)+"\n\n"
            answer="".join(result)
            if not answer: raise InferenceError("EMPTY_INFERENCE_RESPONSE","The inference service returned no response.")
            if answer:
                used_model=llm.local_model if llm.last_provider=="local" and conn.provider_type!="local" else model
                db.add(Message(conversation_id=c.id,role="assistant",content=answer,model_metadata={"model":used_model,"provider":llm.last_provider,"fallback":llm.last_provider!=conn.provider_type,"response_style":body.response_style}))
                if llm.last_provider==conn.provider_type:
                    conn.connection_status="connected"
                db.commit()
            yield "data: "+json.dumps({"type":"done","fallback":llm.last_provider!=conn.provider_type})+"\n\n"
        except Exception as exc:
            db.rollback()
            if conn.provider_type=="kaggle":
                conn.connection_status="disconnected"
                db.commit()
            yield "data: "+json.dumps({"type":"error","code":getattr(exc,"code","INFERENCE_UNAVAILABLE"),"message":"The connection faded. Your message is preserved."})+"\n\n"
    return StreamingResponse(event_stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@router.get("/settings/connection")
def get_connection(db: Session=Depends(session_dependency)):
    c=connection_data(db)
    return {"mode":c.provider_type,"fallback_enabled":c.fallback_enabled,"status":c.connection_status,"model":c.selected_model,"endpoint":c.endpoint_metadata.get("url","")}

@router.put("/settings/connection/kaggle")
def save_manual_kaggle_connection(body: ManualKaggleConnection, db: Session=Depends(session_dependency)):
    from .secret_store import SecretStore, SecretStoreError
    endpoint=body.endpoint.rstrip("/")
    parsed=urlparse(endpoint)
    host=(parsed.hostname or "").lower()
    try: private_host=ipaddress.ip_address(host).is_private
    except ValueError: private_host=host in ("localhost","localhost.localdomain") or host.endswith(".localhost")
    if parsed.scheme!="https" or not host or private_host or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise HTTPException(422,"REMOTE_ENDPOINT_MUST_BE_PUBLIC_HTTPS")
    try:
        store=SecretStore()
        if body.gateway_token:
            if len(body.gateway_token)<24:
                raise HTTPException(422,"GATEWAY_TOKEN_TOO_SHORT")
            store.set("gateway_token",body.gateway_token)
        elif not store.has("gateway_token"):
            raise HTTPException(422,"GATEWAY_TOKEN_REQUIRED")
        # These were used only by removed auto-provisioning and are no longer needed.
        store.delete("kaggle_api_token")
        store.delete("kaggle_username")
    except SecretStoreError as exc:
        raise HTTPException(503,exc.args[0] if exc.args else "LOCAL_CREDENTIAL_STORE_UNAVAILABLE")
    c=connection_data(db)
    c.provider_type="kaggle"
    c.endpoint_metadata={"url":endpoint}
    c.selected_model=body.model.strip()
    c.generation_model=body.model.strip()
    c.fallback_enabled=body.fallback_enabled
    c.connection_status="unknown"
    c.setup_state="MANUAL"
    c.active_setup_job_id=None
    c.kaggle_kernel_id=None
    db.commit()
    return {"saved":True,"mode":"kaggle","status":c.connection_status}

@router.put("/settings/connection")
async def update_connection(body: ConnectionUpdate, db: Session=Depends(session_dependency)):
    from .models import ProviderConnection
    c=connection_data(db)
    endpoint=(body.endpoint or settings.ollama_base_url).rstrip("/")
    parsed=urlparse(endpoint)
    if body.mode=="local" and (parsed.scheme!="http" or parsed.hostname not in ("localhost","127.0.0.1","::1") or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise HTTPException(422,"LOCAL_ENDPOINT_MUST_USE_LOOPBACK")
    try: private_host=ipaddress.ip_address(parsed.hostname or "").is_private
    except ValueError: private_host=(parsed.hostname or "").lower() in ("localhost", "localhost.localdomain") or (parsed.hostname or "").lower().endswith(".localhost")
    if body.mode=="kaggle" and (parsed.scheme!="https" or not parsed.hostname or private_host or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise HTTPException(422,"REMOTE_ENDPOINT_MUST_BE_HTTPS_GATEWAY")
    c.provider_type=body.mode;c.endpoint_metadata={"url":endpoint};c.selected_model=body.selected_model or "";c.generation_model=body.generation_model or "";c.fallback_enabled=body.fallback_enabled;c.connection_status="unknown";db.commit()
    return get_connection(db)

@router.post("/settings/connection/test")
async def test_connection(db: Session=Depends(session_dependency)):
    c,llm=llm_for(db)
    try:
        if c.provider_type=="local":
            from .local_runtime import ensure_local_model
            client=OllamaClient(settings.ollama_base_url,settings.ollama_api_key)
            model=await ensure_local_model(client,c.selected_model or None)
            c.selected_model=model
        else:
            model=c.selected_model or settings.conversation_model
        models=await llm.selected.tags()
        if not model:
            model=recommend_model(models)
        if not model:
            raise InferenceError("MODEL_NOT_CONFIGURED","No model is available for this provider.")
        response=[]
        async for token in llm.selected.chat(model,[{"role":"user","content":"Reply with the single word READY."}]):
            response.append(token)
        if not "".join(response).strip():
            raise InferenceError("INFERENCE_SMOKE_TEST_FAILED","The provider returned an empty response.")
        c.selected_model=model;c.connection_status="connected";db.commit()
        return {"status":"connected","models":[m.get("name") for m in models],"recommended_model":model,"provider":llm.last_provider}
    except InferenceError as exc:
        c.connection_status="disconnected";db.commit();raise HTTPException(503,exc.code)

@router.post("/settings/connection/setup")
async def setup_model(db: Session=Depends(session_dependency)):
    c,llm=llm_for(db)
    if c.provider_type!="local": raise HTTPException(409,"REMOTE_MODEL_SETUP_RUN_IN_NOTEBOOK")
    model=c.selected_model.strip()
    if not model: raise HTTPException(422,"MODEL_NOT_SELECTED")
    async def progress():
        try:
            async for event in llm.pull(model):
                yield "data: "+json.dumps({"type":"progress","status":event.get("status"),"completed":event.get("completed"),"total":event.get("total")})+"\n\n"
            c.connection_status="connected";db.commit()
            yield "data: "+json.dumps({"type":"done","model":model})+"\n\n"
        except Exception as exc:
            db.rollback();yield "data: "+json.dumps({"type":"error","code":getattr(exc,"code","MODEL_DOWNLOAD_FAILED"),"message":"Model setup could not be completed."})+"\n\n"
    return StreamingResponse(progress(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

def recommend_model(models):
    installed=[m.get("name","") for m in models]
    if not installed:return None
    # If memory is unavailable, suggest the smallest installed model by reported size.
    rows=sorted(models,key=lambda m:m.get("size",10**20))
    return rows[0].get("name","")

@router.get("/inference/health")
async def inference_health(db: Session=Depends(session_dependency)):
    c,llm=llm_for(db)
    try: models=await llm.selected.tags();return {"status":"connected","mode":c.provider_type,"models":[m.get("name") for m in models]}
    except InferenceError as exc:return {"status":"disconnected","mode":c.provider_type,"error_code":exc.code}
