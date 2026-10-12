"""Daily cost line items for the seeded company.

Prices are stable per resource and follow rough us-east-1 on-demand rates for
730 hours, or published GB-month storage rates. This is not a real CUR.
"""

import calendar
import hashlib
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from simulator.model import Inventory, ResourceType, SimResource
from simulator.seed import seed_company

# (sku, monthly cents). Compute and database assume 730 hours.
_SKUS: dict[ResourceType, tuple[tuple[str, int], ...]] = {
    ResourceType.compute: (
        ("t3.medium", 3037),
        ("m5.large", 7008),
        ("m5.xlarge", 14016),
    ),
    ResourceType.disk: (
        ("gp3-100gb", 800),
        ("gp3-500gb", 4000),
    ),
    ResourceType.snapshot: (
        ("snapshot-100gb", 500),
        ("snapshot-1tb", 5000),
    ),
    ResourceType.object_storage: (
        ("s3-standard-500gb", 1150),
        ("s3-standard-5tb", 11500),
    ),
    ResourceType.database: (
        ("db.t3.medium", 4964),
        ("db.m5.large", 12483),
    ),
    ResourceType.load_balancer: (("alb", 2227),),
    ResourceType.cluster: (
        ("cluster-2xm5-large", 14016),
        ("cluster-4xm5-large", 28032),
    ),
}


class CostLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    account_id: str = Field(pattern=r"^\d{12}$")
    sku: str = Field(min_length=1)
    day: date
    amount_cents: int = Field(ge=0)
    currency: str = "USD"


def sku_for(resource: SimResource) -> tuple[str, int]:
    if resource.sku is not None:
        cents = _cents_for(resource.resource_type, resource.sku)
        if cents is None:
            raise ValueError(f"unknown sku {resource.sku} for {resource.resource_type}")
        return resource.sku, cents
    options = _SKUS[resource.resource_type]
    digest = hashlib.sha256(resource.resource_id.encode()).digest()
    return options[digest[0] % len(options)]


def _cents_for(resource_type: ResourceType, sku: str) -> int | None:
    for name, cents in _SKUS[resource_type]:
        if name == sku:
            return cents
    return None


def monthly_cents(resource: SimResource) -> int:
    return sku_for(resource)[1]


def daily_costs(inventory: Inventory, account_id: str, year: int, month: int) -> list[CostLine]:
    _require_account(inventory, account_id)
    days = calendar.monthrange(year, month)[1]
    lines: list[CostLine] = []
    for resource in inventory.resources_for(account_id):
        sku, cents = sku_for(resource)
        for day_index, day_cents in enumerate(_split_cents(cents, days), start=1):
            lines.append(
                CostLine(
                    resource_id=resource.resource_id,
                    account_id=account_id,
                    sku=sku,
                    day=date(year, month, day_index),
                    amount_cents=day_cents,
                )
            )
    return lines


def account_month_cents(inventory: Inventory, account_id: str, year: int, month: int) -> int:
    lines = daily_costs(inventory, account_id, year, month)
    return sum(line.amount_cents for line in lines)


def main() -> None:
    inventory = seed_company()
    year, month = 2026, 3
    print(f"billing: {year}-{month:02d}")
    for account in inventory.accounts:
        owned = inventory.resources_for(account.account_id)
        lines = daily_costs(inventory, account.account_id, year, month)
        total = sum(line.amount_cents for line in lines)
        rated = sum(monthly_cents(resource) for resource in owned)
        print(
            f"{account.name}: ${total / 100:.2f} from {len(lines)} daily lines "
            f"(rates ${rated / 100:.2f})"
        )


def _split_cents(total: int, days: int) -> list[int]:
    base, extra = divmod(total, days)
    return [base + (1 if index < extra else 0) for index in range(days)]


def _require_account(inventory: Inventory, account_id: str) -> None:
    if not any(account.account_id == account_id for account in inventory.accounts):
        raise ValueError(f"unknown account {account_id}")


if __name__ == "__main__":
    main()
