"""Match an action, environment, and resource type to an org rule.

The strictest matching effect wins: prohibit, then require_approval, then
allow. When nothing matches, the decision is require_approval. An allow rule
permits the action for a later guarded automation. It does not execute it.
v1 still waits for a person to approve.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.schemas import Policy, PolicyEffect

_STRICTNESS = {
    PolicyEffect.allow: 1,
    PolicyEffect.require_approval: 2,
    PolicyEffect.prohibit: 3,
}


@dataclass(frozen=True)
class Decision:
    effect: PolicyEffect
    name: str | None


def load_policies(text: str) -> list[Policy]:
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("policies"), list):
        raise ValueError("policy file must contain a policies list")
    return [Policy.model_validate(item) for item in loaded["policies"]]


def default_policies() -> list[Policy]:
    path = Path(__file__).with_name("default_policies.yaml")
    return load_policies(path.read_text())


def evaluate(
    policies: Sequence[Policy],
    *,
    action: str,
    environment: str,
    resource_type: str,
) -> Decision:
    matched = [
        policy for policy in policies if _matches(policy, action, environment, resource_type)
    ]
    if not matched:
        return Decision(PolicyEffect.require_approval, None)
    winner = max(matched, key=lambda policy: (_STRICTNESS[policy.effect], policy.name))
    return Decision(winner.effect, winner.name)


def _matches(policy: Policy, action: str, environment: str, resource_type: str) -> bool:
    if not _action_matches(policy, action):
        return False
    if policy.environment is not None and policy.environment.value != environment:
        return False
    if policy.resource_type is not None and policy.resource_type != resource_type:
        return False
    return True


def _action_matches(policy: Policy, action: str) -> bool:
    verb = action.split(maxsplit=1)[0]
    return verb in policy.actions or action in policy.actions
