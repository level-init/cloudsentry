"""Legal approval transitions.

A proposal starts pending. From there it can be approved, rejected, or
cancelled. Any other change is refused, including approving a proposal that
is already approved. There is no reopen flow.
"""

from app.proposals import ApprovalStatus

_ALLOWED: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.pending: frozenset(
        {
            ApprovalStatus.approved,
            ApprovalStatus.rejected,
            ApprovalStatus.cancelled,
        }
    ),
}


def require_transition(current: ApprovalStatus, target: ApprovalStatus) -> None:
    if current == ApprovalStatus.approved and target == ApprovalStatus.approved:
        raise ValueError("cannot re-approve an already approved proposal")
    if target not in _ALLOWED.get(current, frozenset()):
        raise ValueError(f"cannot change approval from {current.value} to {target.value}")
