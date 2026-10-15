import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.proposals import Finding, OptimizationProposal, RiskAssessment

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_proposal.json"


def test_finding_rejects_blank_summary() -> None:
    with pytest.raises(ValidationError):
        Finding(
            finding_id="find-1",
            resource_ids=["i-0a123"],
            category="idle_compute",
            summary="",
        )


def test_risk_assessment_rejects_score_above_one() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(risk_score=1.2, risk_class="APPROVAL_REQUIRED", reasons=["low usage"])


def test_pending_proposal_serializes_to_product_shape() -> None:
    proposal = OptimizationProposal.model_validate_json(_FIXTURE.read_text())

    payload = json.loads(proposal.model_dump_json())
    again = OptimizationProposal.model_validate(payload)

    assert payload["proposal_id"] == "opt-1042"
    assert payload["resource_ids"] == ["i-0a123"]
    assert payload["current_monthly_cost"] == 182.4
    assert payload["predicted_monthly_savings"] == 182.4
    assert payload["confidence"] == 0.94
    assert payload["approval_status"] == "pending"
    assert payload["execution_status"] == "not_started"
    assert payload["verification_status"] == "not_started"
    assert payload["realized_savings"] is None
    assert payload["risk_assessment"]["risk_class"] == "APPROVAL_REQUIRED"
    assert payload["evidence"] == ["average CPU 3.7 percent over 30 days"]
    assert payload["preconditions"] == ["latest backup succeeded"]
    assert payload["execution_steps"] == ["stop the instance outside business hours"]
    assert payload["proposed_actions"] == payload["execution_steps"]
    assert payload["rollback"] == ["start the instance and remove the schedule"]
    assert payload["rollback_plan"] == payload["rollback"]
    assert payload["success_metrics"] == ["monthly cost at or below 0.00"]
    assert again.success_metrics == proposal.success_metrics


def test_incomplete_plan_is_rejected() -> None:
    complete = json.loads(_FIXTURE.read_text())

    for field in ("preconditions", "execution_steps", "rollback", "success_metrics"):
        missing = dict(complete)
        missing.pop(field)
        with pytest.raises(ValidationError):
            OptimizationProposal.model_validate(missing)

    empty = dict(complete)
    empty["preconditions"] = []
    blank = dict(complete)
    blank["success_metrics"] = [" "]
    with pytest.raises(ValidationError):
        OptimizationProposal.model_validate(empty)
    with pytest.raises(ValidationError):
        OptimizationProposal.model_validate(blank)
