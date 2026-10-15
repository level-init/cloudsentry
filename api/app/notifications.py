"""In-app notifications for proposals that are waiting for approval.

The owner and team come from the resource tags. The owner and team columns
are the fallback when a tag is missing. A rejected proposal does not notify.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.proposals import ApprovalStatus, OptimizationProposal
from app.tables import NotificationRow, ResourceRow

PENDING_APPROVAL = "pending_approval"


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: int
    proposal_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    team: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    created_at: datetime


class NotificationList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Notification]


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, owner: str | None = None, team: str | None = None) -> list[Notification]:
        statement = select(NotificationRow).order_by(NotificationRow.notification_id)
        if owner is not None:
            statement = statement.where(NotificationRow.owner == owner)
        if team is not None:
            statement = statement.where(NotificationRow.team == team)
        rows = self.session.scalars(statement).all()
        return [_notification_from_row(row) for row in rows]


def record_pending(session: Session, proposal: OptimizationProposal) -> None:
    if proposal.approval_status != ApprovalStatus.pending:
        return
    seen: set[tuple[str, str]] = set()
    for resource_id in proposal.resource_ids:
        row = session.get(ResourceRow, resource_id)
        if row is None:
            continue
        audience = (
            _tag_or_column(row.tags, "owner", row.owner),
            _tag_or_column(row.tags, "team", row.team),
        )
        if audience in seen:
            continue
        seen.add(audience)
        session.add(
            NotificationRow(
                proposal_id=proposal.proposal_id,
                owner=audience[0],
                team=audience[1],
                kind=PENDING_APPROVAL,
                created_at=datetime.now(timezone.utc),
            )
        )
    if seen:
        session.flush()


def _tag_or_column(tags: dict, name: str, column: str) -> str:
    value = tags.get(name) if isinstance(tags, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return column


def _notification_from_row(row: NotificationRow) -> Notification:
    return Notification(
        notification_id=row.notification_id,
        proposal_id=row.proposal_id,
        owner=row.owner,
        team=row.team,
        kind=row.kind,
        created_at=row.created_at,
    )
