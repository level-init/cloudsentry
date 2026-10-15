"""Deterministic monthly savings for each MVP action.

Inputs are integer cents. The same inputs always return the same savings.
Rates match simulator/simulator/billing.py. A weekday schedule is 40 of 168
hours. Infrequent access is half of standard, using integer division. Resize
uses the monthly rate of the target compute sku.
"""

from dataclasses import dataclass

COMPUTE_CENTS = {"t3.medium": 3037, "m5.large": 7008, "m5.xlarge": 14016}
SCHEDULED_WEEK_HOURS = 40
WEEK_HOURS = 168


@dataclass(frozen=True)
class Savings:
    current_cents: int
    predicted_cents: int

    @property
    def savings_cents(self) -> int:
        return self.current_cents - self.predicted_cents


def stop_savings(current_cents: int) -> Savings:
    _check(current_cents)
    return Savings(current_cents, 0)


def delete_savings(current_cents: int) -> Savings:
    _check(current_cents)
    return Savings(current_cents, 0)


def schedule_savings(current_cents: int) -> Savings:
    _check(current_cents)
    predicted = current_cents * SCHEDULED_WEEK_HOURS // WEEK_HOURS
    return Savings(current_cents, predicted)


def resize_savings(current_cents: int, target_sku: str) -> Savings | None:
    _check(current_cents)
    predicted = COMPUTE_CENTS.get(target_sku)
    if predicted is None:
        return None
    return Savings(current_cents, predicted)


def lifecycle_savings(current_cents: int, action: str) -> Savings | None:
    _check(current_cents)
    if action == "transition-to-infrequent-access":
        return Savings(current_cents, current_cents // 2)
    if action.startswith("expire-after-"):
        return Savings(current_cents, 0)
    return None


def _check(current_cents: int) -> None:
    if current_cents < 0:
        raise ValueError("current monthly cents must be >= 0")
