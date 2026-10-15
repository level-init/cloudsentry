import json
import re
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import OptimizationProposal
from app.repositories import ProposalRepository
from app.tables import FindingRow
from worker.config import Settings, get_settings
from worker.explain import (
    SYSTEM_PROMPT,
    explain,
    explain_stored,
    llm_complete,
    prompt_for,
    stub_narrative,
)

_FIXTURE = Path(__file__).parents[2] / "api" / "tests" / "fixtures" / "sample_proposal.json"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(sqlalchemy_database_url())
    try:
        connection = engine.connect()
    except Exception as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    transaction = connection.begin()
    bound = Session(bind=connection)
    try:
        yield bound
    finally:
        bound.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_prompt_forbids_changing_savings_or_risk_numbers() -> None:
    proposal = _proposal()

    prompt = prompt_for(proposal)

    assert "Do not change the savings or risk numbers" in SYSTEM_PROMPT
    assert "Do not change the savings or risk numbers" in prompt
    assert "Do not invent costs, savings, or risk scores" in prompt
    assert "182.40" in prompt
    assert "0.12" in prompt


def test_stub_explanation_for_the_fixture_keeps_savings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPLAINER", "stub")
    proposal = _proposal()

    narrative = explain(proposal)
    savings = re.search(r"Predicted monthly savings are ([0-9]+\.[0-9]{2})", narrative)
    risk = re.search(r"Risk score is ([0-9]+\.[0-9]{2})", narrative)

    assert savings is not None
    assert risk is not None
    assert float(savings.group(1)) == proposal.predicted_monthly_savings
    assert float(risk.group(1)) == proposal.risk_assessment.risk_score
    assert "stop the instance outside business hours" in narrative


def test_narrative_that_changes_savings_is_rejected() -> None:
    proposal = _proposal()

    def complete(item: OptimizationProposal, _prompt: str) -> str:
        return stub_narrative(item).replace("182.40", "1.00")

    with pytest.raises(ValueError, match="does not match"):
        explain(proposal, complete=complete)


def test_llm_mode_keeps_a_narrative_whose_numbers_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPLAINER", "llm")
    monkeypatch.setenv("EXPLAINER_API_KEY", "test-key")
    proposal = _proposal()

    def complete(prompt: str, _settings: Settings) -> str:
        assert "Do not change the savings or risk numbers" in prompt
        return stub_narrative(proposal)

    monkeypatch.setattr("worker.explain.llm_complete", complete)

    assert explain(proposal) == stub_narrative(proposal)


def test_llm_mode_requires_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPLAINER", "llm")
    monkeypatch.setenv("EXPLAINER_API_KEY", "")

    with pytest.raises(ValueError, match="EXPLAINER_API_KEY"):
        explain(_proposal())


def test_llm_complete_sends_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def read(self) -> bytes:
            body = {"choices": [{"message": {"content": "Predicted monthly savings are 182.40."}}]}
            return json.dumps(body).encode()

    def urlopen(request: urllib.request.Request, timeout: int) -> _Response:
        assert request.data is not None
        seen["body"] = json.loads(request.data.decode())
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("EXPLAINER", "llm")
    monkeypatch.setenv("EXPLAINER_API_KEY", "test-key")
    monkeypatch.setenv("EXPLAINER_MODEL", "test-model")
    monkeypatch.setattr("worker.explain.urllib.request.urlopen", urlopen)
    settings = get_settings()

    text = llm_complete("Use these values exactly.", settings)

    assert "182.40" in text
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    assert body["messages"][0]["content"] == SYSTEM_PROMPT


def test_explanation_is_stored_on_the_proposal(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXPLAINER", "stub")
    proposal = _proposal().model_copy(
        update={"proposal_id": "opt-explain-1", "finding_id": "find-explain-1"}
    )
    session.add(
        FindingRow(
            finding_id="find-explain-1",
            resource_ids=["i-0a123"],
            category="idle_compute",
            summary="idle instance",
            evidence=["average CPU 3.7 percent over 30 days"],
        )
    )
    session.flush()
    ProposalRepository(session).create(proposal)

    stored = explain_stored(session, "opt-explain-1")
    fetched = ProposalRepository(session).get("opt-explain-1")
    savings = re.search(r"Predicted monthly savings are ([0-9]+\.[0-9]{2})", stored.narrative or "")

    assert fetched is not None
    assert savings is not None
    assert float(savings.group(1)) == proposal.predicted_monthly_savings
    assert fetched.narrative == stored.narrative


def _proposal() -> OptimizationProposal:
    return OptimizationProposal.model_validate_json(_FIXTURE.read_text())
