from app.policy import default_policies, evaluate
from app.schemas import Policy, PolicyEffect


def test_default_policies_cover_allow_require_and_prohibit() -> None:
    by_name = {policy.name: policy for policy in default_policies()}

    assert by_name["prohibit-delete-production-database"].effect == PolicyEffect.prohibit
    assert by_name["require-approval-development-schedule"].effect == PolicyEffect.require_approval
    assert by_name["allow-development-stop"].effect == PolicyEffect.allow


def test_delete_production_database_is_prohibited() -> None:
    decision = evaluate(
        default_policies(),
        action="delete db-prd-001",
        environment="production",
        resource_type="database",
    )

    assert decision.effect == PolicyEffect.prohibit
    assert decision.name == "prohibit-delete-production-database"


def test_development_schedule_requires_approval() -> None:
    decision = evaluate(
        default_policies(),
        action="schedule i-dev-026 weekdays-09-17",
        environment="development",
        resource_type="compute",
    )

    assert decision.effect == PolicyEffect.require_approval
    assert decision.name == "require-approval-development-schedule"


def test_development_stop_is_allowed_and_does_not_name_another_rule() -> None:
    decision = evaluate(
        default_policies(),
        action="stop i-dev-062",
        environment="development",
        resource_type="compute",
    )

    assert decision.effect == PolicyEffect.allow
    assert decision.name == "allow-development-stop"


def test_delete_outside_the_production_database_rule_stays_approvable() -> None:
    development = evaluate(
        default_policies(),
        action="delete db-dev-001",
        environment="development",
        resource_type="database",
    )
    disk = evaluate(
        default_policies(),
        action="delete vol-prd-003",
        environment="production",
        resource_type="disk",
    )

    assert development.effect == PolicyEffect.require_approval
    assert development.name is None
    assert disk.effect == PolicyEffect.require_approval
    assert disk.name is None


def test_prohibit_wins_over_a_broader_allow() -> None:
    policies = [
        Policy(name="allow-delete", effect="allow", actions=["delete"]),
        *default_policies(),
    ]

    decision = evaluate(
        policies,
        action="delete db-prd-001",
        environment="production",
        resource_type="database",
    )

    assert decision.effect == PolicyEffect.prohibit
    assert decision.name == "prohibit-delete-production-database"
