from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import CostRecord, Dependency, Incident, Metric, Policy, Resource


def test_resource_accepts_ownership_and_tags() -> None:
    resource = Resource(
        resource_id="i-0a123",
        resource_type="compute_instance",
        account_id="111111111111",
        environment="development",
        owner="payments-team",
        team="payments",
        business_criticality="low",
        tags={"environment": "development"},
    )
    assert resource.owner == "payments-team"
    assert resource.tags["environment"] == "development"


def test_resource_rejects_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Resource(
            resource_id="i-0a123",
            resource_type="compute_instance",
            account_id="111111111111",
            environment="prod",
            owner="payments-team",
            team="payments",
            business_criticality="low",
        )


def test_cost_record_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        CostRecord(
            resource_id="i-0a123",
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            amount=-1,
        )


def test_cost_record_rejects_reversed_period() -> None:
    with pytest.raises(ValidationError):
        CostRecord(
            resource_id="i-0a123",
            period_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
            amount=10,
        )


def test_metric_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        Metric(
            resource_id="i-0a123",
            name="",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            value=1.5,
            unit="percent",
        )


def test_dependency_rejects_self_link() -> None:
    with pytest.raises(ValidationError):
        Dependency(
            source_resource_id="i-0a123",
            target_resource_id="i-0a123",
            relationship="uses",
        )


def test_incident_and_policy_reject_blank_identity() -> None:
    with pytest.raises(ValidationError):
        Incident(
            incident_id="",
            resource_id="i-0a123",
            severity="high",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="database unavailable",
        )
    with pytest.raises(ValidationError):
        Policy(name="protect-prod", effect="not-a-real-effect", actions=["delete"])
