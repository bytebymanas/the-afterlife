import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api
from app.database import Base
from app.models import Conversation, Message, Soul
from app.schemas import MessageCreate


class CapturingInference:
    name = "evaluation"
    last_provider = "evaluation"

    def __init__(self, answer):
        self.answer = answer
        self.messages = None

    async def chat(self, model, messages):
        self.messages = messages
        for token in self.answer:
            yield token


class Connection:
    provider_type = "local"
    selected_model = "evaluation-model"
    fallback_enabled = False


def run_turn(soul_id, name, prompt, history, question, answer):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    soul = Soul(id=soul_id, name=name, canonical_name=name.casefold(), character_prompt=prompt,
                aliases=[], personality_metadata={}, generation_metadata={})
    conversation = Conversation(id="conversation-1", soul=soul, title=name)
    session.add(conversation)
    session.flush()
    for role, content in history:
        session.add(Message(conversation_id=conversation.id, role=role, content=content))
    session.commit()
    inference = CapturingInference(answer)
    original = api.llm_for
    api.llm_for = lambda db: (Connection(), inference)

    async def invoke():
        response = await api.chat(conversation.id, MessageCreate(content=question,
            idempotency_key="eval-turn-0001", response_style="detailed"), session)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    try:
        stream = asyncio.run(invoke())
        assert inference.messages[0] == {"role": "system", "content": prompt}
        assert inference.messages[1:-1] == [{"role": role, "content": content} for role, content in history]
        assert inference.messages[-1] == {"role": "user", "content": question}
        assert f'"text": "{answer[0]}' in stream
        assert '"type": "done"' in stream
        stored = session.query(Message).filter_by(conversation_id=conversation.id, role="assistant").order_by(Message.id.desc()).first()
        assert stored.content == answer
        return inference.messages, stored.content
    finally:
        api.llm_for = original
        session.close()
        engine.dispose()


def test_multi_soul_personality_and_multiturn_system_prompt_evaluation():
    # Three distinct prompt voices, each tested against more than one question.
    scenarios = [
        ("tesla", "Nikola Tesla", "Speak in precise, speculative engineering language. Never claim private memories.",
         "The alternating current motor is a beautiful instrument; its principles are documented, while any private recollection would be beyond this record.",
         [("user", "What do you think of invention?"), ("assistant", "An invention begins as a disciplined image." )],
         "How should its risks be weighed?"),
        ("shelley", "Mary Shelley", "Speak reflectively about creation, responsibility, and loss, with literary cadence.",
         "Creation carries an obligation: the maker must consider the life set loose in the world.",
         [("user", "What does creation ask of us?"), ("assistant", "It asks us to remain beside what we bring forth.")],
         "And when the maker turns away?"),
        ("curie", "Marie Curie", "Speak with disciplined scientific clarity; distinguish evidence from uncertainty.",
         "We should follow the evidence patiently. Where the record is incomplete, certainty would be unscientific.",
         [("user", "How do we approach unknown results?"), ("assistant", "By careful observation and repeated work.")],
         "What if the evidence is still inconclusive?"),
    ]
    outputs = []
    for soul_id, name, prompt, answer, history, question in scenarios:
        payload, streamed_answer = run_turn(soul_id, name, prompt, history, question, answer)
        assert payload[0]["content"] == prompt
        assert streamed_answer == answer
        outputs.append(streamed_answer)
    assert len(set(outputs)) == len(scenarios)
