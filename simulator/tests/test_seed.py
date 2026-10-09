from simulator.model import Environment, ResourceType
from simulator.seed import ACCOUNTS, SEED, reset_seed, seed_company


def test_seed_company_is_repeatable() -> None:
    first = seed_company()
    second = seed_company(SEED)

    assert first.model_dump() == second.model_dump()
    assert reset_seed().model_dump() == first.model_dump()


def test_seed_covers_three_accounts_and_mvp_range() -> None:
    inventory = seed_company()
    environments = {account.environment for account in inventory.accounts}

    assert len(inventory.accounts) == 3
    assert environments == set(Environment)
    assert [account.account_id for account in inventory.accounts] == [
        account.account_id for account in ACCOUNTS
    ]
    assert 100 <= len(inventory.resources) <= 300
    assert len(inventory.resources_for("111111111111")) == 70
    assert len(inventory.resources_for("222222222222")) == 50
    assert len(inventory.resources_for("333333333333")) == 60
    for account in inventory.accounts:
        types = {resource.resource_type for resource in inventory.resources_for(account.account_id)}
        assert types == set(ResourceType)
