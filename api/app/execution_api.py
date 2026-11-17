"""Get an execution run by id."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.execution import ExecutionRun
from app.repositories import ExecutionRunRepository

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get(
    "/{execution_id}",
    response_model=ExecutionRun,
    summary="Get an execution run",
    description=(
        "The run linked to a proposal, including the plan snapshot, status, "
        "and rollback metadata. A missing id returns 404."
    ),
)
def get_execution(
    execution_id: str,
    session: Session = Depends(get_session),
) -> ExecutionRun:
    run = ExecutionRunRepository(session).get(execution_id)
    if run is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return run
