"""List in-app notifications for an owner or a team."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.notifications import NotificationList, NotificationRepository

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=NotificationList,
    summary="List notifications",
    description=(
        "Notifications for proposals waiting on approval. "
        "Filter by owner, team, or both. At least one filter is required. "
        "Owner and team come from the resource tags."
    ),
)
def list_notifications(
    owner: str | None = None,
    team: str | None = None,
    session: Session = Depends(get_session),
) -> NotificationList:
    owner_name = _present(owner)
    team_name = _present(team)
    if owner_name is None and team_name is None:
        raise HTTPException(status_code=422, detail="owner or team is required")
    items = NotificationRepository(session).list(owner=owner_name, team=team_name)
    return NotificationList(items=items)


def _present(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
