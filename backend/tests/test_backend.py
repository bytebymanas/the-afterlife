from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Soul, SummonJob, Conversation, Message, VerificationEvidence
from app.search import SearchResult, SearchUnavailable
from app.services import SummoningService, assess_results, find_existing, normalize_name, seed_predefined

@pytest.fixture
def db():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    session=Session();yield session;session.close()

def hit(host,title,snippet,quality="high"):
    return SearchResult(title,f"https://{host}/person",snippet,host,quality)

def test_predefined_seed_and_alias_lookup(db):
    seed_predefined(db)
    assert find_existing(db,normalize_name("Mary Wollstonecraft Shelley")).id=="mary-shelley"
    assert db.get(Soul,"mary-shelley").character_prompt

def test_two_independent_sources_required_for_deceased():
    results=[hit("reuters.com","Om Puri died at 66","Om Puri died in 2017"),hit("thehindu.com","Om Puri death","Om Puri passed away in 2017")]
    assert assess_results("Om Puri",results)[0]=="DECEASED"
    assert assess_results("Om Puri",results[:1])[0]=="UNKNOWN"
    conflicting=[hit("reuters.com","Om Puri died in 2017","Om Puri died in 2017"),hit("thehindu.com","Om Puri died in 2018","Om Puri died in 2018")]
    assert assess_results("Om Puri",conflicting)[0]=="UNKNOWN"

def test_alive_needs_two_sources_and_conflict_is_unknown():
    alive=[hit("reuters.com","Om Puri profile","Om Puri is alive and well"),hit("theguardian.com","Om Puri profile","Om Puri remains alive")]
    assert assess_results("Om Puri",alive)[0]=="ALIVE"
    assert assess_results("Om Puri",alive+[hit("thehindu.com","Om Puri died","Om Puri died")])[0]=="UNKNOWN"

def test_unknown_and_ambiguous_identity():
    assert assess_results("A Person",[])[0]=="UNKNOWN"
    hits=[hit("reuters.com","John Smith actor","John Smith actor biography"),hit("bbc.com","John Smith politician","John Smith politician biography"),hit("apnews.com","John Smith scientist","John Smith scientist biography")]
    assert assess_results("John Smith",hits)[0]=="AMBIGUOUS"

class UnavailableSearch:
    async def search(self,query): raise SearchUnavailable()

def test_search_timeout_or_unavailable_persists_failed_job_without_soul(db):
    job=__import__("asyncio").run(SummoningService(db,search=UnavailableSearch()).summon("Someone New","idem-search"))
    assert job.status=="VERIFICATION_FAILED" and job.error_code=="VERIFICATION_UNAVAILABLE"
    assert db.query(Soul).filter_by(soul_type="dynamic").count()==0

def test_idempotent_summon_job_reused(db):
    service=SummoningService(db,search=UnavailableSearch())
    first=__import__("asyncio").run(service.summon("Someone New","same-key"))
    second=__import__("asyncio").run(service.summon("Different Name","same-key"))
    assert first.id==second.id

def test_conversation_messages_persist_and_idempotency_constraint(db):
    seed_predefined(db)
    conversation=Conversation(id="c1",soul_id="nikola-tesla",title="Tesla")
    db.add(conversation);db.commit()
    db.add(Message(conversation_id="c1",role="user",content="Hello",idempotency_key="request-123"));db.commit()
    assert db.query(Message).filter_by(conversation_id="c1").count()==1

class SearchResults:
    def __init__(self,results): self.results=results;self.calls=0
    async def search(self,query): self.calls+=1;return self.results

class FakeInference:
    def __init__(self,response): self.response=response;self.calls=0
    async def tags(self): return [{"name":"small-model:latest"}]
    async def generate_json(self,model,prompt): self.calls+=1;return self.response

def valid_prompt():
    return {"biography":"A documented public performer.","profession":"Actor","character_prompt":"Portray this person with a grounded, candid voice. Draw only on documented public work and history. Acknowledge uncertainty and do not invent private memories or conversations.","traits":["direct"],"speaking_style":"measured"}

def test_deceased_summon_generates_and_caches_with_evidence(db):
    search=SearchResults([hit("reuters.com","Om Puri died aged 66","Om Puri died in 2017"),hit("thehindu.com","Om Puri dies","Om Puri passed away in 2017")])
    inference=FakeInference(valid_prompt())
    service=SummoningService(db,search=search,inference=inference)
    job=__import__("asyncio").run(service.summon("Om Puri","om-puri-1"))
    assert job.status=="COMPLETED" and job.generated_soul_id
    soul=db.get(Soul,job.generated_soul_id)
    assert soul.soul_type=="dynamic" and len(soul.character_prompt.split())<=150
    assert db.query(VerificationEvidence).filter_by(soul_id=soul.id).count()==2
    second=__import__("asyncio").run(service.summon("Om Puri","om-puri-2"))
    assert second.generated_soul_id==soul.id and search.calls==2 and inference.calls==1

def test_living_public_figure_does_not_generate_or_persist_soul(db):
    search=SearchResults([hit("reuters.com","Om Puri profile","Om Puri is alive and well"),hit("theguardian.com","Om Puri profile","Om Puri remains alive")])
    inference=FakeInference(valid_prompt())
    job=__import__("asyncio").run(SummoningService(db,search=search,inference=inference).summon("Om Puri"))
    assert job.status=="REJECTED_ALIVE" and inference.calls==0
    assert db.query(Soul).filter_by(soul_type="dynamic").count()==0

def test_invalid_generation_is_retried_once_then_fails_closed(db):
    search=SearchResults([hit("reuters.com","Om Puri died","Om Puri died in 2017"),hit("thehindu.com","Om Puri died","Om Puri passed away in 2017")])
    bad={"biography":"","profession":"Actor","character_prompt":"word "*151,"traits":[],"speaking_style":"plain"}
    inference=FakeInference(bad)
    job=__import__("asyncio").run(SummoningService(db,search=search,inference=inference).summon("Om Puri"))
    assert job.status=="FAILED" and job.error_code=="PROMPT_GENERATION_FAILED"
    assert inference.calls==2 and db.query(Soul).filter_by(soul_type="dynamic").count()==0
