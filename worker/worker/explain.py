"""Write a narrative that repeats the proposal's savings and risk numbers.

The default completer is a stub, so CI does not call a model. EXPLAINER=llm
sends the same prompt to an OpenAI-compatible chat API. A narrative that does
not contain the structured numbers is rejected and is not stored.
"""

import json
import logging
import re
import urllib.request
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db import create_session
from app.proposals import OptimizationProposal
from app.repositories import ProposalRepository
from worker.config import Settings, get_settings

SYSTEM_PROMPT = (
    "Explain this optimization proposal in plain language. "
    "Do not change the savings or risk numbers. "
    "Copy predicted monthly savings, current monthly cost, predicted monthly cost, "
    "and the risk score exactly. Do not invent costs, savings, or risk scores."
)

Complete = Callable[[OptimizationProposal, str], str]


def save_explanations() -> list[OptimizationProposal]:
    session = create_session()
    try:
        stored = explain_all(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    logging.info("explain wrote=%s", len(stored))
    return stored


def explain_all(session: Session) -> list[OptimizationProposal]:
    stored: list[OptimizationProposal] = []
    for proposal in ProposalRepository(session).list():
        stored.append(explain_stored(session, proposal.proposal_id))
    return stored


def explain_stored(session: Session, proposal_id: str) -> OptimizationProposal:
    repository = ProposalRepository(session)
    proposal = repository.get(proposal_id)
    if proposal is None:
        raise ValueError(f"unknown proposal {proposal_id}")
    stored = repository.set_narrative(proposal_id, explain(proposal))
    if stored is None:
        raise ValueError(f"unknown proposal {proposal_id}")
    return stored


def explain(
    proposal: OptimizationProposal,
    *,
    settings: Settings | None = None,
    complete: Complete | None = None,
) -> str:
    settings = get_settings() if settings is None else settings
    complete = _completer(settings) if complete is None else complete
    narrative = complete(proposal, prompt_for(proposal)).strip()
    if not numbers_match(proposal, narrative):
        raise ValueError("narrative savings or risk score does not match the proposal")
    return narrative


def prompt_for(proposal: OptimizationProposal) -> str:
    fields = {
        "proposal_id": proposal.proposal_id,
        "category": proposal.category,
        "resource_ids": list(proposal.resource_ids),
        "current_monthly_cost": _money(proposal.current_monthly_cost),
        "predicted_monthly_cost": _money(proposal.predicted_monthly_cost),
        "predicted_monthly_savings": _money(proposal.predicted_monthly_savings),
        "risk_score": _score(proposal.risk_assessment.risk_score),
        "risk_class": proposal.risk_assessment.risk_class.value,
        "execution_steps": list(proposal.proposed_actions),
        "rollback": list(proposal.rollback_plan),
        "success_metrics": list(proposal.success_metrics),
    }
    return f"{SYSTEM_PROMPT}\nUse these values exactly:\n{json.dumps(fields, indent=2)}"


def stub_narrative(proposal: OptimizationProposal) -> str:
    savings = _money(proposal.predicted_monthly_savings)
    current = _money(proposal.current_monthly_cost)
    predicted = _money(proposal.predicted_monthly_cost)
    score = _score(proposal.risk_assessment.risk_score)
    risk_class = proposal.risk_assessment.risk_class.value
    return (
        f"Proposal {proposal.proposal_id} recommends {proposal.proposed_actions[0]} "
        f"for {proposal.resource_ids[0]}. "
        f"Current monthly cost is {current}. "
        f"Predicted monthly cost is {predicted}. "
        f"Predicted monthly savings are {savings}. "
        f"Risk score is {score} ({risk_class}). "
        f"Rollback is {proposal.rollback_plan[0]}."
    )


def numbers_match(proposal: OptimizationProposal, narrative: str) -> bool:
    tokens = (
        _money(proposal.predicted_monthly_savings),
        _money(proposal.current_monthly_cost),
        _money(proposal.predicted_monthly_cost),
        _score(proposal.risk_assessment.risk_score),
    )
    return all(_has_amount(narrative, token) for token in tokens)


def llm_complete(prompt: str, settings: Settings) -> str:
    if not settings.explainer_api_key:
        raise ValueError("EXPLAINER_API_KEY is required when EXPLAINER=llm")
    body = json.dumps(
        {
            "model": settings.explainer_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode()
    request = urllib.request.Request(
        settings.explainer_base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.explainer_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return str(payload["choices"][0]["message"]["content"])


def _completer(settings: Settings) -> Complete:
    if settings.explainer == "stub":
        return lambda proposal, _prompt: stub_narrative(proposal)

    def complete(_proposal: OptimizationProposal, prompt: str) -> str:
        return llm_complete(prompt, settings)

    return complete


def _money(amount: float) -> str:
    return f"{amount:.2f}"


def _score(score: float) -> str:
    return f"{score:.2f}"


def _has_amount(narrative: str, amount: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(amount)}(?!\d)", narrative) is not None
