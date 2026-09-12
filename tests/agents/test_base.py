from dataclasses import dataclass
from jobagent.agents.base import call_llm
from pydantic import BaseModel
from jobagent.db.session import session_scope
from jobagent.db.models.observability import LLMCall
import pytest

from sqlalchemy.sql.expression import select


class Ping(BaseModel):
    message: str
    ok : bool

@dataclass
class StubPrompt:
    agent : str
    version = "v0"
    model_tier = "small"
    output_schema = Ping
    body = "Réponds avec message='pong' et ok=true."



@pytest.mark.live
def test_llm_call_logs_on_success():
    agent = "test_success"
    result = call_llm(StubPrompt(agent))

    assert isinstance(result, Ping)
    assert result.ok is True

    with session_scope() as session : 
        row = session.scalars(select(LLMCall).where(LLMCall.agent == agent)).first()
        assert row.agent == "test_success"
        assert row.input_tokens > 0
        assert row.cost_usd > 0
        assert row.success is True

def test_llm_call_logs_on_failure():
    agent = "test_failure"
    prompt = StubPrompt(agent)
    prompt.model_tier = "inexistant"
    with pytest.raises(Exception):
        call_llm(prompt)

    with session_scope() as session:
        row = session.scalars(select(LLMCall).where(LLMCall.agent == agent)).first()
        assert row is None