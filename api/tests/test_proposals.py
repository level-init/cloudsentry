import json

import pytest
from pydantic import ValidationError

from app.proposals import Finding, OptimizationProposal, RiskAssessment


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
    proposal = OptimizationProposal(
        proposal_id="opt-1042",
        finding_id="find-1",
        resource_ids=["i-0a123"],
        category="idle_compute",
        current_monthly_cost=182.4,
        predicted_monthly_cost=0,
        predicted_monthly_savings=182.4,
        confidence=0.94,
        business_criticality="low",
        evidence=["average CPU 3.7 percent over 30 days"],
        dependencies=["internal-test-api"],
        preconditions=["latest backup succeeded"],
        proposed_actions=["stop the instance outside business hours"],
        rollback_plan=["start the instance and remove the schedule"],
        risk_assessment=RiskAssessment(
            risk_score=0.12,
            risk_class="APPROVAL_REQUIRED",
            reasons=["development environment with no production dependencies"],
        ),
    )

    payload = json.loads(proposal.model_dump_json())

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
    assert payload["rollback_plan"] == ["start the instance and remove the schedule"]
