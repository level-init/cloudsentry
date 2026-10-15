"""List, filter, get, approve, reject, queue, and audit optimization proposals.

Until sign-in exists, the caller sends the actor in the X-Actor header.
The API trusts that header. The body carries the reason.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_session
from app.proposals import (
    ApprovalDecision,
    ApprovalStatus,
    OptimizationProposal,
    ProposalList,
    RiskClass,
)
from app.repositories import ProposalRepository
from app.schemas import Environment

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ApprovalReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is required")
        return stripped


@router.get(
    "",
    response_model=ProposalList,
    summary="List proposals",
    description=(
        "Filters are approval status, risk class, resource environment, resource team, "
        "and proposal category. Results are ordered by proposal id. "
        "limit defaults to 50 and cannot exceed 100. offset defaults to 0. "
        "total is the full match count before that page."
    ),
)
def list_proposals(
    status: ApprovalStatus | None = None,
    risk_class: RiskClass | None = None,
    environment: Environment | None = None,
    team: str | None = None,
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> ProposalList:
    page = ProposalRepository(session).page(
        approval_status=None if status is None else status.value,
        risk_class=None if risk_class is None else risk_class.value,
        environment=None if environment is None else environment.value,
        team=team,
        category=category,
        limit=limit,
        offset=offset,
    )
    return ProposalList(items=list(page.items), total=page.total, limit=limit, offset=offset)


@router.get(
    "/{proposal_id}",
    response_model=OptimizationProposal,
    summary="Get a proposal",
    description="The full proposal, including the plan, risk assessment, and narrative.",
)
def get_proposal(proposal_id: str, session: Session = Depends(get_session)) -> OptimizationProposal:
    proposal = ProposalRepository(session).get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return proposal


@router.post(
    "/{proposal_id}/approve",
    response_model=OptimizationProposal,
    summary="Approve a proposal",
    description=(
        "Moves a pending proposal to approved and stores the actor, time, and reason. "
        "Send the actor in the X-Actor header. That header is the assumed identity "
        "until sign-in exists. A rejected risk class, a prohibit policy, or any "
        "approval change other than pending to approved is refused."
    ),
)
def approve_proposal(
    proposal_id: str,
    body: ApprovalReason,
    x_actor: Annotated[str, Header(alias="X-Actor")],
    session: Session = Depends(get_session),
) -> OptimizationProposal:
    return _decide(proposal_id, ApprovalStatus.approved, body, x_actor, session)


@router.post(
    "/{proposal_id}/reject",
    response_model=OptimizationProposal,
    summary="Reject a proposal",
    description=(
        "Moves a pending proposal to rejected and stores the actor, time, and reason. "
        "Send the actor in the X-Actor header. That header is the assumed identity "
        "until sign-in exists."
    ),
)
def reject_proposal(
    proposal_id: str,
    body: ApprovalReason,
    x_actor: Annotated[str, Header(alias="X-Actor")],
    session: Session = Depends(get_session),
) -> OptimizationProposal:
    return _decide(proposal_id, ApprovalStatus.rejected, body, x_actor, session)


@router.post(
    "/{proposal_id}/execute",
    response_model=OptimizationProposal,
    summary="Queue an approved proposal",
    description=(
        "Accepts an approved proposal into the execution queue. "
        "A pending, rejected, or cancelled proposal is refused, including "
        "SAFE_AUTOMATION. A prohibit policy is refused. "
        "This does not change the simulator."
    ),
)
def execute_proposal(
    proposal_id: str,
    session: Session = Depends(get_session),
) -> OptimizationProposal:
    try:
        updated = ProposalRepository(session).begin_execution(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return updated


@router.get(
    "/{proposal_id}/audit",
    response_model=list[ApprovalDecision],
    summary="List the approval audit",
    description=(
        "Approval changes for this proposal, oldest first. "
        "Each approve or reject appends one row. "
        "Rows cannot be updated or deleted."
    ),
)
def list_audit(
    proposal_id: str,
    session: Session = Depends(get_session),
) -> list[ApprovalDecision]:
    repository = ProposalRepository(session)
    if repository.get(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return list(repository.decisions(proposal_id))


def _decide(
    proposal_id: str,
    target: ApprovalStatus,
    body: ApprovalReason,
    actor: str,
    session: Session,
) -> OptimizationProposal:
    name = actor.strip()
    if not name:
        raise HTTPException(status_code=422, detail="X-Actor is required")
    try:
        updated = ProposalRepository(session).update_status(
            proposal_id,
            approval_status=target,
            actor=name,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return updated
