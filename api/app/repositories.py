"""Persistence for resources and optimization proposals."""

from datetime import date

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.proposals import (
    ApprovalStatus,
    ExecutionStatus,
    OptimizationProposal,
    RiskAssessment,
    VerificationStatus,
)
from app.schemas import MetricRollup, Resource
from app.tables import FindingRow, MetricRollupRow, ProposalRow, ResourceRow, RiskAssessmentRow


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
        self.session.flush()
        return False

    def get(self, resource_id: str) -> Resource | None:
        row = self.session.get(ResourceRow, resource_id)
        if row is None:
            return None
        return _resource_from_row(row)

    def list(self, environment: str | None = None) -> list[Resource]:
        statement = select(ResourceRow)
        if environment is not None:
            statement = statement.where(ResourceRow.environment == environment)
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


def _chunks(rollups: list[MetricRollup], size: int) -> list[list[MetricRollup]]:
    return [rollups[index : index + size] for index in range(0, len(rollups), size)]


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
