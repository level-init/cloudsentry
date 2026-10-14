"""Persistence for resources and optimization proposals."""

from datetime import date, datetime, timezone
from typing import TypeVar

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.proposals import (
    ApprovalStatus,
    ExecutionStatus,
    Finding,
    OptimizationProposal,
    RiskAssessment,
    VerificationStatus,
)
from app.schemas import CostRecord, Dependency, DetectionRun, Incident, MetricRollup, Resource
from app.tables import (
    CostRecordRow,
    DependencyRow,
    DetectionRunRow,
    FindingRow,
    IncidentRow,
    MetricRollupRow,
    ProposalRow,
    ResourceRow,
    RiskAssessmentRow,
)


class ResourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, resource: Resource) -> Resource:
        self.session.add(
            ResourceRow(
                resource_id=resource.resource_id,
                resource_type=resource.resource_type,
                account_id=resource.account_id,
                environment=resource.environment.value,
                owner=resource.owner,
                team=resource.team,
                business_criticality=resource.business_criticality.value,
                tags=resource.tags,
                present=True,
                sku=resource.sku,
                storage_class=resource.storage_class,
            )
        )
        self.session.flush()
        return resource

    def upsert(self, resource: Resource) -> bool:
        row = self.session.get(ResourceRow, resource.resource_id)
        if row is None:
            self.create(resource)
            return True
        row.resource_type = resource.resource_type
        row.account_id = resource.account_id
        row.environment = resource.environment.value
        row.owner = resource.owner
        row.team = resource.team
        row.business_criticality = resource.business_criticality.value
        row.tags = dict(resource.tags)
        row.present = True
        row.sku = resource.sku
        row.storage_class = resource.storage_class
        self.session.flush()
        return False

    def mark_absent(self, present_ids: set[str]) -> int:
        rows = self.session.scalars(select(ResourceRow).where(ResourceRow.present.is_(True))).all()
        marked = 0
        for row in rows:
            if row.resource_id not in present_ids:
                row.present = False
                marked += 1
        self.session.flush()
        return marked

    def get(self, resource_id: str) -> Resource | None:
        row = self.session.get(ResourceRow, resource_id)
        if row is None:
            return None
        return _resource_from_row(row)

    def list(
        self,
        environment: str | None = None,
        account_id: str | None = None,
        resource_type: str | None = None,
    ) -> list[Resource]:
        statement = select(ResourceRow)
        if environment is not None:
            statement = statement.where(ResourceRow.environment == environment)
        if account_id is not None:
            statement = statement.where(ResourceRow.account_id == account_id)
        if resource_type is not None:
            statement = statement.where(ResourceRow.resource_type == resource_type)
        rows = self.session.scalars(statement.order_by(ResourceRow.resource_id)).all()
        return [_resource_from_row(row) for row in rows]


class MetricRollupRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, rollups: list[MetricRollup]) -> tuple[int, int]:
        if not rollups:
            return 0, 0
        created = 0
        for chunk in _chunks(rollups, 500):
            created += len(chunk) - _existing_rollups(self.session, chunk)
            self.session.execute(_rollup_insert(chunk))
        self.session.flush()
        return created, len(rollups) - created

    def summarize(
        self,
        resource_id: str,
        name: str,
        start: date,
        end: date,
    ) -> tuple[float, float]:
        if end <= start:
            raise ValueError("end must be after start")
        rows = self.session.scalars(
            select(MetricRollupRow)
            .where(
                MetricRollupRow.resource_id == resource_id,
                MetricRollupRow.name == name,
                MetricRollupRow.day >= start,
                MetricRollupRow.day < end,
            )
            .order_by(MetricRollupRow.day)
        ).all()
        if not rows:
            raise ValueError(f"no {name} rollups for {resource_id}")
        average = sum(row.avg_value for row in rows) / len(rows)
        peak = max(row.peak_value for row in rows)
        return average, peak

    def utilization(
        self,
        resource_ids: list[str],
        name: str,
        start: date,
        end: date,
    ) -> dict[str, tuple[float, float]]:
        if not resource_ids or end <= start:
            return {}
        rows = self.session.execute(
            select(
                MetricRollupRow.resource_id,
                func.avg(MetricRollupRow.avg_value),
                func.max(MetricRollupRow.peak_value),
            )
            .where(
                MetricRollupRow.resource_id.in_(resource_ids),
                MetricRollupRow.name == name,
                MetricRollupRow.day >= start,
                MetricRollupRow.day < end,
            )
            .group_by(MetricRollupRow.resource_id)
        ).all()
        return {resource_id: (float(average), float(peak)) for resource_id, average, peak in rows}

    def latest_day(self, name: str) -> date | None:
        return self.session.scalar(
            select(func.max(MetricRollupRow.day)).where(MetricRollupRow.name == name)
        )

    def window_summary(
        self,
        resource_ids: list[str],
        name: str,
        start: date,
        end: date,
    ) -> dict[str, tuple[float, float, int]]:
        if not resource_ids or end <= start:
            return {}
        rows = self.session.execute(
            select(
                MetricRollupRow.resource_id,
                func.avg(MetricRollupRow.avg_value),
                func.max(MetricRollupRow.peak_value),
                func.count(),
            )
            .where(
                MetricRollupRow.resource_id.in_(resource_ids),
                MetricRollupRow.name == name,
                MetricRollupRow.day >= start,
                MetricRollupRow.day < end,
            )
            .group_by(MetricRollupRow.resource_id)
        ).all()
        return {
            resource_id: (float(average), float(peak), int(days))
            for resource_id, average, peak, days in rows
        }

    def daily_averages(
        self,
        resource_ids: list[str],
        name: str,
        start: date,
        end: date,
    ) -> dict[str, list[tuple[date, float]]]:
        if not resource_ids or end <= start:
            return {}
        rows = self.session.execute(
            select(MetricRollupRow.resource_id, MetricRollupRow.day, MetricRollupRow.avg_value)
            .where(
                MetricRollupRow.resource_id.in_(resource_ids),
                MetricRollupRow.name == name,
                MetricRollupRow.day >= start,
                MetricRollupRow.day < end,
            )
            .order_by(MetricRollupRow.resource_id, MetricRollupRow.day)
        ).all()
        grouped: dict[str, list[tuple[date, float]]] = {}
        for resource_id, day, average in rows:
            grouped.setdefault(resource_id, []).append((day, float(average)))
        return grouped

    def count(self, resource_id: str, name: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(MetricRollupRow)
                .where(
                    MetricRollupRow.resource_id == resource_id,
                    MetricRollupRow.name == name,
                )
            )
            or 0
        )


class CostRecordRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, records: list[CostRecord]) -> tuple[int, int]:
        if not records:
            return 0, 0
        created = 0
        for chunk in _chunks(records, 500):
            created += len(chunk) - _existing_costs(self.session, chunk)
            self.session.execute(_cost_insert(chunk))
        self.session.flush()
        return created, len(records) - created

    def monthly_cents(
        self,
        year: int,
        month: int,
        *,
        resource_id: str | None = None,
        account_id: str | None = None,
    ) -> int:
        start, end = _month_bounds(year, month)
        statement = (
            select(CostRecordRow.amount)
            .join(ResourceRow, ResourceRow.resource_id == CostRecordRow.resource_id)
            .where(CostRecordRow.period_start >= start, CostRecordRow.period_start < end)
        )
        if resource_id is not None:
            statement = statement.where(CostRecordRow.resource_id == resource_id)
        if account_id is not None:
            statement = statement.where(ResourceRow.account_id == account_id)
        amounts = self.session.scalars(statement).all()
        return sum(_cents(amount) for amount in amounts)

    def monthly_cents_by_resource(
        self,
        year: int,
        month: int,
        resource_ids: list[str],
    ) -> dict[str, int]:
        if not resource_ids:
            return {}
        start, end = _month_bounds(year, month)
        rows = self.session.execute(
            select(CostRecordRow.resource_id, CostRecordRow.amount).where(
                CostRecordRow.resource_id.in_(resource_ids),
                CostRecordRow.period_start >= start,
                CostRecordRow.period_start < end,
            )
        ).all()
        totals: dict[str, int] = {}
        for resource_id, amount in rows:
            totals[resource_id] = totals.get(resource_id, 0) + _cents(amount)
        return totals

    def monthly_cents_by_account(self, year: int, month: int) -> dict[str, int]:
        return _monthly_cents_grouped(self.session, year, month, ResourceRow.account_id)

    def monthly_cents_by_environment(self, year: int, month: int) -> dict[str, int]:
        return _monthly_cents_grouped(self.session, year, month, ResourceRow.environment)

    def age_and_latest_month_cents(self, resource_ids: list[str]) -> dict[str, tuple[int, int]]:
        if not resource_ids:
            return {}
        rows = self.session.execute(
            select(
                CostRecordRow.resource_id,
                CostRecordRow.period_start,
                CostRecordRow.amount,
            ).where(CostRecordRow.resource_id.in_(resource_ids))
        ).all()
        grouped: dict[str, list[tuple[datetime, float]]] = {}
        for resource_id, period_start, amount in rows:
            grouped.setdefault(resource_id, []).append((period_start, float(amount)))
        summaries: dict[str, tuple[int, int]] = {}
        for resource_id, samples in grouped.items():
            oldest = min(period for period, _amount in samples)
            latest = max(period for period, _amount in samples)
            age_days = (latest.date() - oldest.date()).days
            month_cents = sum(
                _cents(amount)
                for period, amount in samples
                if period.year == latest.year and period.month == latest.month
            )
            summaries[resource_id] = (age_days, month_cents)
        return summaries

    def latest_month(self) -> tuple[int, int] | None:
        latest = self.session.scalar(select(func.max(CostRecordRow.period_start)))
        if latest is None:
            return None
        return latest.year, latest.month

    def count(self, resource_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(CostRecordRow)
                .where(CostRecordRow.resource_id == resource_id)
            )
            or 0
        )


class DependencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, edges: list[Dependency]) -> tuple[int, int]:
        if not edges:
            return 0, 0
        created = 0
        for chunk in _chunks(edges, 500):
            created += len(chunk) - _existing_edges(self.session, chunk)
            self.session.execute(_edge_insert(chunk))
        self.session.flush()
        return created, len(edges) - created

    def targets_with_dependents(self, resource_ids: list[str]) -> set[str]:
        if not resource_ids:
            return set()
        rows = self.session.scalars(
            select(DependencyRow.target_resource_id)
            .where(DependencyRow.target_resource_id.in_(resource_ids))
            .distinct()
        ).all()
        return set(rows)

    def dependencies_of(self, resource_id: str) -> list[Dependency]:
        rows = self.session.scalars(
            select(DependencyRow)
            .where(DependencyRow.source_resource_id == resource_id)
            .order_by(DependencyRow.relationship, DependencyRow.target_resource_id)
        ).all()
        return [_dependency_from_row(row) for row in rows]

    def dependents_of(self, resource_id: str) -> list[Dependency]:
        rows = self.session.scalars(
            select(DependencyRow)
            .where(DependencyRow.target_resource_id == resource_id)
            .order_by(DependencyRow.relationship, DependencyRow.source_resource_id)
        ).all()
        return [_dependency_from_row(row) for row in rows]


class IncidentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, incidents: list[Incident]) -> tuple[int, int]:
        if not incidents:
            return 0, 0
        created = 0
        for chunk in _chunks(incidents, 500):
            created += len(chunk) - _existing_incidents(self.session, chunk)
            self.session.execute(_incident_insert(chunk))
        self.session.flush()
        return created, len(incidents) - created

    def for_resource(self, resource_id: str) -> list[Incident]:
        rows = self.session.scalars(
            select(IncidentRow)
            .where(IncidentRow.resource_id == resource_id)
            .order_by(IncidentRow.started_at, IncidentRow.incident_id)
        ).all()
        return [_incident_from_row(row) for row in rows]


class DetectionRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        trigger: str,
        interval_seconds: int,
        started_at: datetime,
        finished_at: datetime,
        detectors: int,
        created: int,
        updated: int,
        findings: int,
    ) -> DetectionRun:
        row = DetectionRunRow(
            trigger=trigger,
            interval_seconds=interval_seconds,
            started_at=started_at,
            finished_at=finished_at,
            detectors=detectors,
            created=created,
            updated=updated,
            findings=findings,
        )
        self.session.add(row)
        self.session.flush()
        return _detection_run_from_row(row)

    def get(self, run_id: int) -> DetectionRun | None:
        row = self.session.get(DetectionRunRow, run_id)
        if row is None:
            return None
        return _detection_run_from_row(row)


class FindingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, finding: Finding) -> bool:
        row = self.session.get(FindingRow, finding.finding_id)
        if row is None:
            self.session.add(
                FindingRow(
                    finding_id=finding.finding_id,
                    resource_ids=list(finding.resource_ids),
                    category=finding.category,
                    summary=finding.summary,
                    evidence=list(finding.evidence),
                )
            )
            self.session.flush()
            return True
        row.resource_ids = list(finding.resource_ids)
        row.category = finding.category
        row.summary = finding.summary
        row.evidence = list(finding.evidence)
        self.session.flush()
        return False

    def get(self, finding_id: str) -> Finding | None:
        row = self.session.get(FindingRow, finding_id)
        if row is None:
            return None
        return _finding_from_row(row)


class ProposalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, proposal: OptimizationProposal) -> OptimizationProposal:
        finding = self.session.get(FindingRow, proposal.finding_id)
        if finding is None:
            raise ValueError(f"finding {proposal.finding_id} does not exist")
        self.session.add(_proposal_row(proposal))
        self.session.add(_risk_row(proposal))
        self.session.flush()
        return proposal

    def get(self, proposal_id: str) -> OptimizationProposal | None:
        row = self.session.get(ProposalRow, proposal_id)
        if row is None:
            return None
        risk = self.session.scalar(
            select(RiskAssessmentRow).where(RiskAssessmentRow.proposal_id == proposal_id)
        )
        if risk is None:
            return None
        return _proposal_from_rows(row, risk)

    def list(self, approval_status: str | None = None) -> list[OptimizationProposal]:
        statement = select(ProposalRow, RiskAssessmentRow).join(
            RiskAssessmentRow,
            RiskAssessmentRow.proposal_id == ProposalRow.proposal_id,
        )
        if approval_status is not None:
            statement = statement.where(ProposalRow.approval_status == approval_status)
        statement = statement.order_by(ProposalRow.proposal_id)
        return [
            _proposal_from_rows(proposal, risk)
            for proposal, risk in self.session.execute(statement)
        ]

    def update_status(
        self,
        proposal_id: str,
        *,
        approval_status: ApprovalStatus | None = None,
        execution_status: ExecutionStatus | None = None,
        verification_status: VerificationStatus | None = None,
    ) -> OptimizationProposal | None:
        row = self.session.get(ProposalRow, proposal_id)
        if row is None:
            return None
        if approval_status is not None:
            row.approval_status = approval_status.value
        if execution_status is not None:
            row.execution_status = execution_status.value
        if verification_status is not None:
            row.verification_status = verification_status.value
        self.session.flush()
        return self.get(proposal_id)


_Item = TypeVar("_Item")


def _chunks(items: list[_Item], size: int) -> list[list[_Item]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _monthly_cents_grouped(session: Session, year: int, month: int, column) -> dict[str, int]:
    start, end = _month_bounds(year, month)
    rows = session.execute(
        select(column, CostRecordRow.amount)
        .join(ResourceRow, ResourceRow.resource_id == CostRecordRow.resource_id)
        .where(CostRecordRow.period_start >= start, CostRecordRow.period_start < end)
    ).all()
    totals: dict[str, int] = {}
    for key, amount in rows:
        totals[key] = totals.get(key, 0) + _cents(amount)
    return totals


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    if not 1 <= month <= 12:
        raise ValueError("month must be from 1 to 12")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _cents(amount: float) -> int:
    return int(round(amount * 100))


def _existing_costs(session: Session, records: list[CostRecord]) -> int:
    keys = [(record.resource_id, record.period_start) for record in records]
    found = session.scalar(
        select(func.count())
        .select_from(CostRecordRow)
        .where(tuple_(CostRecordRow.resource_id, CostRecordRow.period_start).in_(keys))
    )
    return int(found or 0)


def _cost_insert(records: list[CostRecord]):
    statement = insert(CostRecordRow).values(
        [
            {
                "resource_id": record.resource_id,
                "period_start": record.period_start,
                "period_end": record.period_end,
                "amount": record.amount,
                "currency": record.currency,
            }
            for record in records
        ]
    )
    return statement.on_conflict_do_update(
        constraint="uq_cost_records_resource_period",
        set_={
            "period_end": statement.excluded.period_end,
            "amount": statement.excluded.amount,
            "currency": statement.excluded.currency,
        },
    )


def _existing_rollups(session: Session, rollups: list[MetricRollup]) -> int:
    keys = [(rollup.resource_id, rollup.name, rollup.day) for rollup in rollups]
    found = session.scalar(
        select(func.count())
        .select_from(MetricRollupRow)
        .where(
            tuple_(MetricRollupRow.resource_id, MetricRollupRow.name, MetricRollupRow.day).in_(keys)
        )
    )
    return int(found or 0)


def _rollup_insert(rollups: list[MetricRollup]):
    statement = insert(MetricRollupRow).values(
        [
            {
                "resource_id": rollup.resource_id,
                "name": rollup.name,
                "day": rollup.day,
                "avg_value": rollup.avg_value,
                "peak_value": rollup.peak_value,
                "unit": rollup.unit,
            }
            for rollup in rollups
        ]
    )
    return statement.on_conflict_do_update(
        constraint="uq_metric_rollups_resource_name_day",
        set_={
            "avg_value": statement.excluded.avg_value,
            "peak_value": statement.excluded.peak_value,
            "unit": statement.excluded.unit,
        },
    )


def _existing_edges(session: Session, edges: list[Dependency]) -> int:
    keys = [(edge.source_resource_id, edge.target_resource_id, edge.relationship) for edge in edges]
    found = session.scalar(
        select(func.count())
        .select_from(DependencyRow)
        .where(
            tuple_(
                DependencyRow.source_resource_id,
                DependencyRow.target_resource_id,
                DependencyRow.relationship,
            ).in_(keys)
        )
    )
    return int(found or 0)


def _edge_insert(edges: list[Dependency]):
    statement = insert(DependencyRow).values(
        [
            {
                "source_resource_id": edge.source_resource_id,
                "target_resource_id": edge.target_resource_id,
                "relationship": edge.relationship,
            }
            for edge in edges
        ]
    )
    return statement.on_conflict_do_nothing(constraint="uq_dependencies_edge")


def _existing_incidents(session: Session, incidents: list[Incident]) -> int:
    keys = [incident.incident_id for incident in incidents]
    found = session.scalar(
        select(func.count()).select_from(IncidentRow).where(IncidentRow.incident_id.in_(keys))
    )
    return int(found or 0)


def _incident_insert(incidents: list[Incident]):
    statement = insert(IncidentRow).values(
        [
            {
                "incident_id": incident.incident_id,
                "resource_id": incident.resource_id,
                "severity": incident.severity.value,
                "started_at": incident.started_at,
                "summary": incident.summary,
            }
            for incident in incidents
        ]
    )
    return statement.on_conflict_do_update(
        index_elements=["incident_id"],
        set_={
            "resource_id": statement.excluded.resource_id,
            "severity": statement.excluded.severity,
            "started_at": statement.excluded.started_at,
            "summary": statement.excluded.summary,
        },
    )


def _detection_run_from_row(row: DetectionRunRow) -> DetectionRun:
    return DetectionRun(
        run_id=row.run_id,
        trigger=row.trigger,
        interval_seconds=row.interval_seconds,
        started_at=row.started_at,
        finished_at=row.finished_at,
        detectors=row.detectors,
        created=row.created,
        updated=row.updated,
        findings=row.findings,
    )


def _finding_from_row(row: FindingRow) -> Finding:
    return Finding(
        finding_id=row.finding_id,
        resource_ids=list(row.resource_ids),
        category=row.category,
        summary=row.summary,
        evidence=list(row.evidence),
    )


def _dependency_from_row(row: DependencyRow) -> Dependency:
    return Dependency(
        source_resource_id=row.source_resource_id,
        target_resource_id=row.target_resource_id,
        relationship=row.relationship,
    )


def _incident_from_row(row: IncidentRow) -> Incident:
    return Incident(
        incident_id=row.incident_id,
        resource_id=row.resource_id,
        severity=row.severity,
        started_at=row.started_at,
        summary=row.summary,
    )


def _resource_from_row(row: ResourceRow) -> Resource:
    return Resource(
        resource_id=row.resource_id,
        resource_type=row.resource_type,
        account_id=row.account_id,
        environment=row.environment,
        owner=row.owner,
        team=row.team,
        business_criticality=row.business_criticality,
        tags=row.tags,
        present=row.present,
        sku=row.sku,
        storage_class=row.storage_class,
    )


def _proposal_row(proposal: OptimizationProposal) -> ProposalRow:
    return ProposalRow(
        proposal_id=proposal.proposal_id,
        finding_id=proposal.finding_id,
        resource_ids=proposal.resource_ids,
        category=proposal.category,
        current_monthly_cost=proposal.current_monthly_cost,
        predicted_monthly_cost=proposal.predicted_monthly_cost,
        predicted_monthly_savings=proposal.predicted_monthly_savings,
        confidence=proposal.confidence,
        business_criticality=proposal.business_criticality.value,
        evidence=proposal.evidence,
        dependencies=proposal.dependencies,
        preconditions=proposal.preconditions,
        proposed_actions=proposal.proposed_actions,
        rollback_plan=proposal.rollback_plan,
        approval_status=proposal.approval_status.value,
        execution_status=proposal.execution_status.value,
        verification_status=proposal.verification_status.value,
        realized_savings=proposal.realized_savings,
    )


def _risk_row(proposal: OptimizationProposal) -> RiskAssessmentRow:
    risk = proposal.risk_assessment
    return RiskAssessmentRow(
        proposal_id=proposal.proposal_id,
        risk_score=risk.risk_score,
        risk_class=risk.risk_class.value,
        reasons=risk.reasons,
    )


def _proposal_from_rows(row: ProposalRow, risk: RiskAssessmentRow) -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id=row.proposal_id,
        finding_id=row.finding_id,
        resource_ids=row.resource_ids,
        category=row.category,
        current_monthly_cost=row.current_monthly_cost,
        predicted_monthly_cost=row.predicted_monthly_cost,
        predicted_monthly_savings=row.predicted_monthly_savings,
        confidence=row.confidence,
        business_criticality=row.business_criticality,
        evidence=row.evidence,
        dependencies=row.dependencies,
        preconditions=row.preconditions,
        proposed_actions=row.proposed_actions,
        rollback_plan=row.rollback_plan,
        approval_status=row.approval_status,
        execution_status=row.execution_status,
        verification_status=row.verification_status,
        realized_savings=row.realized_savings,
        risk_assessment=RiskAssessment(
            risk_score=risk.risk_score,
            risk_class=risk.risk_class,
            reasons=risk.reasons,
        ),
    )
