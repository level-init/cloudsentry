"""Persistence for resources and optimization proposals."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TypeVar

from sqlalchemy import exists, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.approval import require_transition
from app.execution import (
    ExecutionEvent,
    ExecutionEventType,
    ExecutionRun,
    is_terminal,
    require_run_transition,
)
from app.notifications import record_pending
from app.policy import Decision, default_policies, evaluate
from app.proposals import (
    ApprovalDecision,
    ApprovalStatus,
    ExecutionStatus,
    Finding,
    OptimizationProposal,
    RiskAssessment,
    RiskClass,
    VerificationStatus,
)
from app.schemas import (
    CostRecord,
    Dependency,
    DetectionRun,
    Incident,
    MetricRollup,
    Policy,
    PolicyEffect,
    Resource,
)
from app.tables import (
    ApprovalDecisionRow,
    CostRecordRow,
    DependencyRow,
    DetectionRunRow,
    ExecutionEventRow,
    ExecutionRunRow,
    FindingRow,
    IncidentRow,
    MetricRollupRow,
    PolicyRow,
    ProposalRow,
    ResourceRow,
    RiskAssessmentRow,
)
from app.terraform_gen import write_change


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

    def list(self) -> list[Finding]:
        rows = self.session.scalars(select(FindingRow).order_by(FindingRow.finding_id)).all()
        return [_finding_from_row(row) for row in rows]


class PolicyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self) -> list[Policy]:
        rows = self.session.scalars(select(PolicyRow).order_by(PolicyRow.name)).all()
        return [_policy_from_row(row) for row in rows]

    def upsert(self, policy: Policy) -> bool:
        row = self.session.get(PolicyRow, policy.name)
        created = row is None
        if row is None:
            self.session.add(_policy_row(policy))
        else:
            row.effect = policy.effect.value
            row.actions = list(policy.actions)
            row.environment = _environment_value(policy)
            row.resource_type = policy.resource_type
        self.session.flush()
        return created

    def seed_defaults(self) -> Sequence[str]:
        added: list[str] = []
        for policy in default_policies():
            if self.session.get(PolicyRow, policy.name) is None:
                self.upsert(policy)
                added.append(policy.name)
        return added


@dataclass(frozen=True)
class ProposalPage:
    items: Sequence[OptimizationProposal]
    total: int


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
        record_pending(self.session, proposal)
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
        items, _total = self._query(approval_status=approval_status)
        return list(items)

    def page(
        self,
        *,
        approval_status: str | None = None,
        risk_class: str | None = None,
        environment: str | None = None,
        team: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProposalPage:
        items, total = self._query(
            approval_status=approval_status,
            risk_class=risk_class,
            environment=environment,
            team=team,
            category=category,
            limit=limit,
            offset=offset,
        )
        return ProposalPage(items=items, total=total)

    def _query(
        self,
        *,
        approval_status: str | None = None,
        risk_class: str | None = None,
        environment: str | None = None,
        team: str | None = None,
        category: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[Sequence[OptimizationProposal], int]:
        statement = select(ProposalRow, RiskAssessmentRow).join(
            RiskAssessmentRow,
            RiskAssessmentRow.proposal_id == ProposalRow.proposal_id,
        )
        if approval_status is not None:
            statement = statement.where(ProposalRow.approval_status == approval_status)
        if risk_class is not None:
            statement = statement.where(RiskAssessmentRow.risk_class == risk_class)
        if category is not None:
            statement = statement.where(ProposalRow.category == category)
        if environment is not None:
            statement = statement.where(_linked_resource(ResourceRow.environment == environment))
        if team is not None:
            statement = statement.where(_linked_resource(ResourceRow.team == team))
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        statement = statement.order_by(ProposalRow.proposal_id)
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        rows = self.session.execute(statement).all()
        return [_proposal_from_rows(proposal, risk) for proposal, risk in rows], total

    def find_with_action(
        self, resource_ids: Sequence[str], action: str
    ) -> OptimizationProposal | None:
        for proposal in self.list():
            if list(proposal.resource_ids) == list(resource_ids) and proposal.proposed_actions == [
                action
            ]:
                return proposal
        return None

    def find_open(self, resource_ids: Sequence[str], action: str) -> OptimizationProposal | None:
        for proposal in self.list(approval_status=ApprovalStatus.pending.value):
            if list(proposal.resource_ids) == list(resource_ids) and proposal.proposed_actions == [
                action
            ]:
                return proposal
        return None

    def update_status(
        self,
        proposal_id: str,
        *,
        approval_status: ApprovalStatus | None = None,
        execution_status: ExecutionStatus | None = None,
        verification_status: VerificationStatus | None = None,
        actor: str | None = None,
        reason: str | None = None,
        decided_at: datetime | None = None,
    ) -> OptimizationProposal | None:
        row = self.session.get(ProposalRow, proposal_id)
        if row is None:
            return None
        current = ApprovalStatus(row.approval_status)
        if approval_status is not None:
            require_transition(current, approval_status)
        blocked = _rejected_execution_blocked(
            self.session, proposal_id, approval_status, execution_status
        )
        if blocked:
            raise ValueError(f"rejected proposal {proposal_id} cannot be approved into execution")
        prohibited = _prohibited_execution(
            self.session, proposal_id, approval_status, execution_status
        )
        if prohibited is not None:
            raise ValueError(f"policy {prohibited} prohibits {proposal_id}")
        resulting = approval_status if approval_status is not None else current
        if _execution_requested(execution_status) and resulting != ApprovalStatus.approved:
            raise ValueError(f"proposal {proposal_id} must be approved before execution")
        if approval_status is not None:
            actor_name, decision_reason = _require_decision(actor, reason)
            when = datetime.now(timezone.utc) if decided_at is None else decided_at
            self.session.add(
                ApprovalDecisionRow(
                    proposal_id=proposal_id,
                    actor=actor_name,
                    reason=decision_reason,
                    decided_at=when,
                    from_status=current.value,
                    to_status=approval_status.value,
                )
            )
            row.approval_status = approval_status.value
        if execution_status is not None:
            row.execution_status = execution_status.value
        if verification_status is not None:
            row.verification_status = verification_status.value
        self.session.flush()
        return self.get(proposal_id)

    def decisions(self, proposal_id: str) -> Sequence[ApprovalDecision]:
        rows = self.session.scalars(
            select(ApprovalDecisionRow)
            .where(ApprovalDecisionRow.proposal_id == proposal_id)
            .order_by(ApprovalDecisionRow.decision_id)
        ).all()
        return [_decision_from_row(row) for row in rows]

    def begin_execution(self, proposal_id: str, *, actor: str) -> OptimizationProposal | None:
        current = self.get(proposal_id)
        if current is None:
            return None
        if current.approval_status != ApprovalStatus.approved:
            raise ValueError(f"proposal {proposal_id} must be approved before execution")
        if current.execution_status != ExecutionStatus.not_started:
            prohibited = _prohibited_execution(
                self.session,
                proposal_id,
                ApprovalStatus.approved,
                ExecutionStatus.queued,
            )
            if prohibited is not None:
                raise ValueError(f"policy {prohibited} prohibits {proposal_id}")
            return current
        name = actor.strip()
        if not name:
            raise ValueError("execution requires an actor")
        updated = self.update_status(proposal_id, execution_status=ExecutionStatus.queued)
        if updated is None:
            return None
        ExecutionRunRepository(self.session).create_queued(updated, actor=name)
        return updated

    def set_narrative(self, proposal_id: str, narrative: str) -> OptimizationProposal | None:
        row = self.session.get(ProposalRow, proposal_id)
        if row is None:
            return None
        row.narrative = narrative
        self.session.flush()
        return self.get(proposal_id)


class ExecutionRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_queued(self, proposal: OptimizationProposal, *, actor: str) -> ExecutionRun:
        existing = self.for_proposal(proposal.proposal_id)
        if existing is not None:
            return existing
        when = datetime.now(timezone.utc)
        artifact = write_change(proposal, created_at=when)
        row = ExecutionRunRow(
            execution_id=_execution_id(proposal.proposal_id),
            proposal_id=proposal.proposal_id,
            status=ExecutionStatus.queued.value,
            actor=actor.strip(),
            plan_snapshot=list(proposal.proposed_actions),
            started_at=when,
            finished_at=None,
            rollback_plan=list(proposal.rollback_plan),
            rollback_reason=None,
            rolled_back_by=None,
            artifact_path=artifact.path,
            artifact_hash=artifact.hash,
            artifact_created_at=artifact.created_at,
            applied_action_ids=[],
        )
        self.session.add(row)
        self.session.flush()
        return _execution_from_row(row)

    def set_applied_action_ids(
        self, execution_id: str, action_ids: Sequence[str]
    ) -> ExecutionRun | None:
        row = self.session.get(ExecutionRunRow, execution_id)
        if row is None:
            return None
        row.applied_action_ids = list(action_ids)
        self.session.flush()
        return _execution_from_row(row)

    def get(self, execution_id: str) -> ExecutionRun | None:
        row = self.session.get(ExecutionRunRow, execution_id)
        if row is None:
            return None
        return _execution_from_row(row)

    def for_proposal(self, proposal_id: str) -> ExecutionRun | None:
        row = self.session.scalar(
            select(ExecutionRunRow)
            .where(ExecutionRunRow.proposal_id == proposal_id)
            .order_by(ExecutionRunRow.started_at, ExecutionRunRow.execution_id)
        )
        if row is None:
            return None
        return _execution_from_row(row)

    def update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
        *,
        rollback_reason: str | None = None,
        rolled_back_by: str | None = None,
        finished_at: datetime | None = None,
    ) -> ExecutionRun | None:
        row = self.session.get(ExecutionRunRow, execution_id)
        if row is None:
            return None
        current = ExecutionStatus(row.status)
        require_run_transition(current, status)
        if status == ExecutionStatus.rolled_back:
            who = None if rolled_back_by is None else rolled_back_by.strip()
            why = None if rollback_reason is None else rollback_reason.strip()
            if not who or not why:
                raise ValueError("rollback requires rolled_back_by and rollback_reason")
            row.rolled_back_by = who
            row.rollback_reason = why
        row.status = status.value
        if is_terminal(status):
            row.finished_at = datetime.now(timezone.utc) if finished_at is None else finished_at
        proposal = self.session.get(ProposalRow, row.proposal_id)
        if proposal is not None:
            proposal.execution_status = status.value
        self.session.flush()
        return _execution_from_row(row)

    def append_event(
        self,
        *,
        execution_id: str,
        proposal_id: str,
        event_type: ExecutionEventType,
        actor: str,
        reason: str,
        from_status: ExecutionStatus,
        to_status: ExecutionStatus,
        occurred_at: datetime | None = None,
    ) -> ExecutionEvent:
        name = actor.strip()
        why = reason.strip()
        if not name or not why:
            raise ValueError("execution audit requires an actor and a reason")
        when = datetime.now(timezone.utc) if occurred_at is None else occurred_at
        row = ExecutionEventRow(
            execution_id=execution_id,
            proposal_id=proposal_id,
            event_type=event_type.value,
            actor=name,
            reason=why,
            occurred_at=when,
            from_status=from_status.value,
            to_status=to_status.value,
        )
        self.session.add(row)
        self.session.flush()
        return _execution_event_from_row(row)

    def events(self, execution_id: str) -> Sequence[ExecutionEvent]:
        rows = self.session.scalars(
            select(ExecutionEventRow)
            .where(ExecutionEventRow.execution_id == execution_id)
            .order_by(ExecutionEventRow.event_id)
        ).all()
        return [_execution_event_from_row(row) for row in rows]


def _execution_id(proposal_id: str) -> str:
    return f"execution-{proposal_id}"


def _execution_from_row(row: ExecutionRunRow) -> ExecutionRun:
    return ExecutionRun(
        execution_id=row.execution_id,
        proposal_id=row.proposal_id,
        status=row.status,
        actor=row.actor,
        plan_snapshot=list(row.plan_snapshot),
        started_at=row.started_at,
        finished_at=row.finished_at,
        rollback_plan=list(row.rollback_plan),
        rollback_reason=row.rollback_reason,
        rolled_back_by=row.rolled_back_by,
        artifact_path=row.artifact_path,
        artifact_hash=row.artifact_hash,
        artifact_created_at=row.artifact_created_at,
        applied_action_ids=list(row.applied_action_ids or []),
    )


def _execution_event_from_row(row: ExecutionEventRow) -> ExecutionEvent:
    return ExecutionEvent(
        execution_id=row.execution_id,
        proposal_id=row.proposal_id,
        event_type=row.event_type,
        actor=row.actor,
        reason=row.reason,
        occurred_at=row.occurred_at,
        from_status=row.from_status,
        to_status=row.to_status,
    )


def _require_decision(actor: str | None, reason: str | None) -> tuple[str, str]:
    if actor is None or not actor.strip() or reason is None or not reason.strip():
        raise ValueError("approval changes require an actor and a reason")
    return actor.strip(), reason.strip()


def _decision_from_row(row: ApprovalDecisionRow) -> ApprovalDecision:
    return ApprovalDecision(
        proposal_id=row.proposal_id,
        actor=row.actor,
        reason=row.reason,
        decided_at=row.decided_at,
        from_status=row.from_status,
        to_status=row.to_status,
    )


def _linked_resource(criterion):
    return exists(
        select(ResourceRow.resource_id).where(
            criterion,
            ProposalRow.resource_ids.contains(func.jsonb_build_array(ResourceRow.resource_id)),
        )
    )


def _rejected_execution_blocked(
    session: Session,
    proposal_id: str,
    approval_status: ApprovalStatus | None,
    execution_status: ExecutionStatus | None,
) -> bool:
    if not _starts_execution(approval_status, execution_status):
        return False
    risk = session.scalar(
        select(RiskAssessmentRow).where(RiskAssessmentRow.proposal_id == proposal_id)
    )
    if risk is None or risk.risk_class != RiskClass.rejected.value:
        return False
    return not _override_allows_rejected(session)


def _execution_requested(execution_status: ExecutionStatus | None) -> bool:
    return execution_status in {
        ExecutionStatus.queued,
        ExecutionStatus.running,
        ExecutionStatus.succeeded,
    }


def _starts_execution(
    approval_status: ApprovalStatus | None,
    execution_status: ExecutionStatus | None,
) -> bool:
    if approval_status == ApprovalStatus.approved:
        return True
    return _execution_requested(execution_status)


def _prohibited_execution(
    session: Session,
    proposal_id: str,
    approval_status: ApprovalStatus | None,
    execution_status: ExecutionStatus | None,
) -> str | None:
    if not _starts_execution(approval_status, execution_status):
        return None
    proposal = session.get(ProposalRow, proposal_id)
    if proposal is None:
        return None
    policies = PolicyRepository(session).list()
    for resource_id in proposal.resource_ids:
        resource = session.get(ResourceRow, resource_id)
        if resource is None:
            continue
        for action in proposal.proposed_actions:
            decision = _decision(policies, action, resource)
            if decision.effect == PolicyEffect.prohibit:
                return decision.name
    return None


def _decision(policies: Sequence[Policy], action: str, resource: ResourceRow) -> Decision:
    return evaluate(
        policies,
        action=action,
        environment=resource.environment,
        resource_type=resource.resource_type,
    )


def _policy_from_row(row: PolicyRow) -> Policy:
    return Policy(
        name=row.name,
        effect=row.effect,
        actions=list(row.actions),
        environment=row.environment,
        resource_type=row.resource_type,
    )


def _policy_row(policy: Policy) -> PolicyRow:
    return PolicyRow(
        name=policy.name,
        effect=policy.effect.value,
        actions=list(policy.actions),
        environment=_environment_value(policy),
        resource_type=policy.resource_type,
    )


def _environment_value(policy: Policy) -> str | None:
    if policy.environment is None:
        return None
    return policy.environment.value


def _override_allows_rejected(session: Session) -> bool:
    rows = session.scalars(select(PolicyRow)).all()
    return any(row.effect == "allow" and "approve_rejected" in row.actions for row in rows)


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
        success_metrics=proposal.success_metrics,
        narrative=proposal.narrative,
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
        success_metrics=row.success_metrics,
        narrative=row.narrative,
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
