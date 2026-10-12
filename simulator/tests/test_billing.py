from simulator.billing import account_month_cents, daily_costs, monthly_cents, sku_for
from simulator.model import ResourceType
from simulator.seed import seed_company


def test_every_resource_has_a_positive_monthly_rate() -> None:
    inventory = seed_company()

    for resource in inventory.resources:
        sku, cents = sku_for(resource)
        assert cents == monthly_cents(resource)
        assert cents > 0
        assert sku
        assert cents == _known_rates()[resource.resource_type][sku]


def test_march_account_total_matches_daily_lines_and_rates() -> None:
    inventory = seed_company()
    account_id = "111111111111"
    lines = daily_costs(inventory, account_id, 2026, 3)
    owned = inventory.resources_for(account_id)

    assert len(lines) == len(owned) * 31
    assert sum(line.amount_cents for line in lines) == account_month_cents(
        inventory, account_id, 2026, 3
    )
    assert account_month_cents(inventory, account_id, 2026, 3) == sum(
        monthly_cents(resource) for resource in owned
    )


def test_company_spend_is_the_sum_of_account_spend() -> None:
    inventory = seed_company()
    accounts = [account.account_id for account in inventory.accounts]
    account_sum = sum(
        account_month_cents(inventory, account_id, 2026, 3) for account_id in accounts
    )

    assert account_sum == sum(monthly_cents(resource) for resource in inventory.resources)
    assert len(accounts) == 3


def test_one_resource_daily_cents_sum_to_its_monthly_rate() -> None:
    inventory = seed_company()
    resource = inventory.resources[0]
    lines = [
        line
        for line in daily_costs(inventory, resource.account_id, 2026, 3)
        if line.resource_id == resource.resource_id
    ]

    assert sum(line.amount_cents for line in lines) == monthly_cents(resource)
    assert {line.day.month for line in lines} == {3}


def _known_rates() -> dict[ResourceType, dict[str, int]]:
    return {
        ResourceType.compute: {"t3.medium": 3037, "m5.large": 7008, "m5.xlarge": 14016},
        ResourceType.disk: {"gp3-100gb": 800, "gp3-500gb": 4000},
        ResourceType.snapshot: {"snapshot-100gb": 500, "snapshot-1tb": 5000},
        ResourceType.object_storage: {"s3-standard-500gb": 1150, "s3-standard-5tb": 11500},
        ResourceType.database: {"db.t3.medium": 4964, "db.m5.large": 12483},
        ResourceType.load_balancer: {"alb": 2227},
        ResourceType.cluster: {"cluster-2xm5-large": 14016, "cluster-4xm5-large": 28032},
    }
