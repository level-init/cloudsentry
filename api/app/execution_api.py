"""Get an execution run by id and list its append-only audit."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.execution import ExecutionEvent, ExecutionRun
from app.repositories import ExecutionRunRepository

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get(
    "/{execution_id}/audit",
    response_model=list[ExecutionEvent],
    summary="List the execution audit",
    description=(
        "Apply and rollback events for this run, oldest first. "
        "Each successful apply or rollback appends one row. "
        "Rows cannot be updated or deleted."
    ),
)
def list_execution_audit(
    execution_id: str,
    session: Session = Depends(get_session),
) -> list[ExecutionEvent]:
    runs = ExecutionRunRepository(session)
    if runs.get(execution_id) is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return list(runs.events(execution_id))


@router.get(
    "/{execution_id}",
    response_model=ExecutionRun,
    summary="Get an execution run",
    description=(
        "The run linked to a proposal, including the plan snapshot, status, "
        "rollback metadata, the reviewable Terraform change path, and the "
        "pre-change baseline when apply has captured one. "
        "artifact_path is the fake-repo directory under terraform/changes. "
        "artifact_hash and artifact_created_at are the commit-like metadata. "
        "baseline holds cost and cpu_percent windows captured before mutate. "
        "A missing id returns 404."
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
