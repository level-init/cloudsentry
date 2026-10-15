"""List, filter, and get optimization proposals."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.proposals import (
    ApprovalStatus,
    OptimizationProposal,
    ProposalList,
    RiskClass,
)
from app.repositories import ProposalRepository
from app.schemas import Environment

router = APIRouter(prefix="/proposals", tags=["proposals"])


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
