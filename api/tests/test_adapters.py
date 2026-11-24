from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters import (
    ApplyError,
    SimulatorApplyAdapter,
    apply_action_to_run,
    apply_plan_action,
)
from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, ExecutionStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, ProposalRepository
from app.tables import FindingRow
from simulator.main import create_app
from tests.support import simulator_request


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


@pytest.fixture
def adapter() -> SimulatorApplyAdapter:
    client = TestClient(create_app())
    return SimulatorApplyAdapter(base_url="http://simulator", request=simulator_request(client))


def test_each_mvp_plan_action_applies_through_the_adapter(adapter: SimulatorApplyAdapter) -> None:
    stopped = apply_plan_action(adapter, "stop i-dev-062")
    assert stopped.changed is True
    assert adapter._resource("i-dev-062")["power_state"] == "stopped"
    assert apply_plan_action(adapter, "stop i-dev-062").changed is False
    assert adapter.rollback(stopped.action_id).changed is True
    assert adapter._resource("i-dev-062")["power_state"] == "running"

    resized = apply_plan_action(adapter, "resize i-prd-013 to m5.large")
    assert resized.changed is True
    assert adapter._resource("i-prd-013")["sku"] == "m5.large"
    assert apply_plan_action(adapter, "resize i-prd-013 to m5.large").changed is False
    assert adapter.rollback(resized.action_id).changed is True
    assert adapter._resource("i-prd-013")["sku"] == "m5.xlarge"

    scheduled = apply_plan_action(adapter, "schedule i-dev-026 weekdays-09-17")
    assert scheduled.changed is True
    assert adapter._resource("i-dev-026")["schedule"] == "weekdays-09-17"
    assert apply_plan_action(adapter, "schedule i-dev-026 weekdays-09-17").changed is False
    assert adapter.rollback(scheduled.action_id).changed is True
    assert adapter._resource("i-dev-026")["schedule"] == "always_on"

    deleted = apply_plan_action(adapter, "delete vol-dev-042")
    assert deleted.changed is True
    assert adapter._resource("vol-dev-042") is None
    assert apply_plan_action(adapter, "delete vol-dev-042").changed is False
    assert adapter.rollback(deleted.action_id).changed is True
    assert adapter._resource("vol-dev-042") is not None

    changed = apply_plan_action(adapter, "transition bucket-prd-022 to infrequent_access")
    assert changed.changed is True
    assert adapter._resource("bucket-prd-022")["storage_class"] == "infrequent_access"
    assert (
        apply_plan_action(adapter, "transition bucket-prd-022 to infrequent_access").changed
        is False
    )
    assert adapter.rollback(changed.action_id).changed is True
    assert adapter._resource("bucket-prd-022")["storage_class"] == "standard"


def test_adapter_failures_mark_the_execution_run_failed(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    session.add(
        FindingRow(
            finding_id="find-i2",
            resource_ids=["i-dev-062"],
            category="idle_compute",
            summary="idle instance",
            evidence=["low cpu"],
        )
    )
    session.flush()
    proposals = ProposalRepository(session)
    proposals.create(_proposal())
    proposals.update_status(
        "opt-i2",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="ready to stop",
    )
    proposals.begin_execution("opt-i2", actor="ada")
    runs = ExecutionRunRepository(session)

    with pytest.raises(ApplyError, match="applies only to compute"):
        apply_action_to_run(session, "execution-opt-i2", "stop vol-dev-042", adapter)

    failed = runs.get("execution-opt-i2")
    assert failed is not None
    assert failed.status == ExecutionStatus.failed
    assert failed.finished_at is not None
    assert proposals.get("opt-i2").execution_status == "failed"


def test_unsupported_plan_action_is_refused(adapter: SimulatorApplyAdapter) -> None:
    with pytest.raises(ApplyError, match="unsupported"):
        apply_plan_action(adapter, "expire snap-dev-007")


def _proposal() -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id="opt-i2",
        finding_id="find-i2",
        resource_ids=["i-dev-062"],
        category="idle_compute",
        current_monthly_cost=30.37,
        predicted_monthly_cost=0,
        predicted_monthly_savings=30.37,
        confidence=0.8,
        business_criticality="low",
        evidence=["low cpu"],
        preconditions=["compute is present"],
        proposed_actions=["stop i-dev-062"],
        rollback_plan=["start i-dev-062"],
        success_metrics=["monthly cost at or below 0.00"],
        approval_status="pending",
        risk_assessment=RiskAssessment(
            risk_score=0.05,
            risk_class="SAFE_AUTOMATION",
            reasons=["development resource"],
        ),
    )
