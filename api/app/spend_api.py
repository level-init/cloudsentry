"""Monthly spend totals by account and by environment."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.repositories import CostRecordRepository
from app.schemas import (
    AccountSpend,
    AccountSpendReport,
    Environment,
    EnvironmentSpend,
    EnvironmentSpendReport,
)

router = APIRouter(prefix="/spend", tags=["inventory"])


@router.get(
    "/accounts",
    response_model=AccountSpendReport,
    summary="Spend by account",
    description=(
        "Monthly cost in cents for each account that has cost records in the month. "
        "total_cents is the sum of those accounts. Omit year and month to use the "
        "latest month that has cost records. Set year and month together."
    ),
)
def spend_by_account(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    session: Session = Depends(get_session),
) -> AccountSpendReport:
    chosen = _chosen_month(session, year, month)
    if chosen is None:
        return AccountSpendReport(items=[], total_cents=0)
    totals = CostRecordRepository(session).monthly_cents_by_account(*chosen)
    items = [
        AccountSpend(account_id=account_id, monthly_cost_cents=cents)
        for account_id, cents in sorted(totals.items())
    ]
    return AccountSpendReport(
        year=chosen[0],
        month=chosen[1],
        items=items,
        total_cents=sum(item.monthly_cost_cents for item in items),
    )


@router.get(
    "/environments",
    response_model=EnvironmentSpendReport,
    summary="Spend by environment",
    description=(
        "Monthly cost in cents for each environment that has cost records in the month. "
        "total_cents is the sum of those environments. Omit year and month to use the "
        "latest month that has cost records. Set year and month together."
    ),
)
def spend_by_environment(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    session: Session = Depends(get_session),
) -> EnvironmentSpendReport:
    chosen = _chosen_month(session, year, month)
    if chosen is None:
        return EnvironmentSpendReport(items=[], total_cents=0)
    totals = CostRecordRepository(session).monthly_cents_by_environment(*chosen)
    items = [
        EnvironmentSpend(environment=Environment(environment), monthly_cost_cents=cents)
        for environment, cents in sorted(
            totals.items(),
            key=lambda item: _environment_order(item[0]),
        )
    ]
    return EnvironmentSpendReport(
        year=chosen[0],
        month=chosen[1],
        items=items,
        total_cents=sum(item.monthly_cost_cents for item in items),
    )


def _chosen_month(
    session: Session,
    year: int | None,
    month: int | None,
) -> tuple[int, int] | None:
    if (year is None) != (month is None):
        raise HTTPException(status_code=422, detail="year and month are set together")
    if year is not None and month is not None:
        return year, month
    return CostRecordRepository(session).latest_month()


def _environment_order(environment: str) -> tuple[int, str]:
    try:
        return (list(Environment).index(Environment(environment)), environment)
    except ValueError:
        return (len(Environment), environment)
