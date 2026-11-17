import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, ProposalRepository
from app.tables import FindingRow
from app.terraform_gen import generate_hcl, write_change


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


def test_schedule_and_resize_hcl_include_the_proposal_id(tmp_path: Path) -> None:
    schedule = _proposal(
        "opt-i3-schedule",
        "find-i3-schedule",
        "i-dev-026",
        "development_scheduling",
        ["schedule i-dev-026 weekdays-09-17"],
    )
    resize = _proposal(
        "opt-i3-resize",
        "find-i3-resize",
        "i-prd-013",
        "compute_rightsizing",
        ["resize i-prd-013 to m5.large"],
    )

    schedule_text = generate_hcl(schedule)
    resize_text = generate_hcl(resize)
    schedule_artifact = write_change(schedule, root=tmp_path)
    resize_artifact = write_change(resize, root=tmp_path)
    schedule_main = Path(schedule_artifact.path) / "main.tf"
    resize_main = Path(resize_artifact.path) / "main.tf"

    assert "CloudSentry proposal: opt-i3-schedule" in schedule_text
    assert "Action: schedule i-dev-026 weekdays-09-17" in schedule_text
    assert 'Schedule = "weekdays-09-17"' in schedule_text
    assert schedule_main.read_text(encoding="utf-8") == schedule_text
    assert "CloudSentry proposal: opt-i3-resize" in resize_text
    assert "Action: resize i-prd-013 to m5.large" in resize_text
    assert 'instance_type = "m5.large"' in resize_text
    assert resize_main.read_text(encoding="utf-8") == resize_text


def test_versioned_artifact_records_commit_metadata(tmp_path: Path) -> None:
    proposal = _proposal(
        "opt-i4",
        "find-i4",
        "i-dev-026",
        "development_scheduling",
        ["schedule i-dev-026 weekdays-09-17"],
    )

    artifact = write_change(proposal, root=tmp_path)
    directory = Path(artifact.path)
    commit = json.loads((directory / "commit.json").read_text(encoding="utf-8"))

    assert directory.is_dir()
    assert (directory / "main.tf").exists()
    assert artifact.hash == commit["hash"]
    assert artifact.hash.startswith(directory.name)
    assert commit["proposal_id"] == "opt-i4"
    assert commit["files"] == ["main.tf"]
    assert commit["review_path"] == artifact.path
    assert "created_at" in commit
    assert set(directory.iterdir()) >= {directory / "main.tf", directory / "commit.json"}


def test_execute_stores_the_artifact_path(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    session.add(
        FindingRow(
            finding_id="find-i3",
            resource_ids=["i-dev-026"],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    proposals = ProposalRepository(session)
    proposals.create(
        _proposal(
            "opt-i3",
            "find-i3",
            "i-dev-026",
            "development_scheduling",
            ["schedule i-dev-026 weekdays-09-17"],
        )
    )
    proposals.update_status(
        "opt-i3",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="development schedule is allowed",
    )

    proposals.begin_execution("opt-i3", actor="ada")
    run = ExecutionRunRepository(session).for_proposal("opt-i3")

    assert run is not None
    assert run.artifact_path is not None
    assert run.artifact_hash is not None
    assert run.artifact_created_at is not None
    path = Path(run.artifact_path)
    assert path.is_dir()
    text = (path / "main.tf").read_text(encoding="utf-8")
    commit = json.loads((path / "commit.json").read_text(encoding="utf-8"))
    assert "CloudSentry proposal: opt-i3" in text
    assert "Action: schedule i-dev-026 weekdays-09-17" in text
    assert commit["hash"] == run.artifact_hash
    assert commit["review_path"] == run.artifact_path


def _proposal(
    proposal_id: str,
    finding_id: str,
    resource_id: str,
    category: str,
    actions: list[str],
) -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id=proposal_id,
        finding_id=finding_id,
        resource_ids=[resource_id],
        category=category,
        current_monthly_cost=70.08,
        predicted_monthly_cost=16.68,
        predicted_monthly_savings=53.4,
        confidence=0.8,
        business_criticality="low",
        evidence=["planted for terraform"],
        preconditions=["resource is present"],
        proposed_actions=actions,
        rollback_plan=[f"restore {resource_id}"],
        success_metrics=["monthly cost drops"],
        approval_status="pending",
        risk_assessment=RiskAssessment(
            risk_score=0.05,
            risk_class="SAFE_AUTOMATION",
            reasons=["development resource"],
        ),
    )
