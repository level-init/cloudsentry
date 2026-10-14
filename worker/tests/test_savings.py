import pytest

from worker.savings import (
    delete_savings,
    lifecycle_savings,
    resize_savings,
    schedule_savings,
    stop_savings,
)


def test_each_mvp_action_saves_the_same_cents_twice() -> None:
    assert _twice(stop_savings, 3037) == (0, 3037)
    assert _twice(delete_savings, 4000) == (0, 4000)
    assert _twice(schedule_savings, 7008) == (1668, 5340)
    assert _twice(lambda cents: resize_savings(cents, "m5.large"), 14016) == (7008, 7008)
    transition = _twice(
        lambda cents: lifecycle_savings(cents, "transition-to-infrequent-access"),
        11500,
    )
    assert transition == (5750, 5750)
    expired = _twice(lambda cents: lifecycle_savings(cents, "expire-after-90-days"), 5000)
    assert expired == (0, 5000)


def test_unknown_resize_and_lifecycle_actions_have_no_savings() -> None:
    assert resize_savings(14016, "m5.2xlarge") is None
    assert lifecycle_savings(11500, "intelligent-tiering") is None


def test_negative_current_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        stop_savings(-1)


def _twice(calculator, cents: int) -> tuple[int, int]:
    first = calculator(cents)
    second = calculator(cents)
    assert first == second
    assert first.savings_cents == first.current_cents - first.predicted_cents
    return first.predicted_cents, first.savings_cents
