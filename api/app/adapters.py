"""Apply adapters for approved plan steps.

The simulator implements CloudApplyAdapter over HTTP. The API talks to that
HTTP surface. It does not import the simulator package. Failures raise
ApplyError so a caller can mark the ExecutionRun failed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_settings

Requester = Callable[[str, str, dict | None], tuple[int, object]]


class ApplyError(ValueError):
    """A mutate call failed or the plan action is unknown."""


class PolicyProhibitedError(ApplyError):
    """Fail closed when a live prohibit policy blocks mutate."""

    code = "policy_prohibited"

    def __init__(self, policy_name: str, proposal_id: str) -> None:
        self.policy_name = policy_name
        self.proposal_id = proposal_id
        super().__init__(f"{self.code}: policy {policy_name} prohibits {proposal_id}")


@dataclass(frozen=True)
class MutationResult:
    action_id: str
    action: str
    resource_id: str
    changed: bool
    resource: dict | None


class CloudApplyAdapter(Protocol):
    def stop(self, resource_id: str) -> MutationResult: ...

    def start(self, resource_id: str) -> MutationResult: ...

    def resize(self, resource_id: str, sku: str) -> MutationResult: ...

    def schedule(self, resource_id: str, schedule: str) -> MutationResult: ...

    def delete_unattached(self, resource_id: str) -> MutationResult: ...

    def storage_lifecycle(self, resource_id: str, storage_class: str) -> MutationResult: ...

    def rollback(self, action_id: str) -> MutationResult: ...


class SimulatorApplyAdapter:
    """HTTP apply adapter for the local simulator."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        request: Requester | None = None,
        mutate_token: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.simulator_base_url).rstrip("/")
        token = (settings.simulator_mutate_token if mutate_token is None else mutate_token).strip()
        if request is not None:
            self._request = request
        else:
            self._request = lambda method, url, body: _http_request(
                method, url, body, token or None
            )

    def stop(self, resource_id: str) -> MutationResult:
        current = self._resource(resource_id)
        if current is not None and current.get("power_state") == "stopped":
            return _unchanged("stop", resource_id, current)
        return self._mutate("POST", f"/resources/{resource_id}/actions/stop")

    def start(self, resource_id: str) -> MutationResult:
        current = self._resource(resource_id)
        if current is not None and current.get("power_state") == "running":
            return _unchanged("start", resource_id, current)
        return self._mutate("POST", f"/resources/{resource_id}/actions/start")

    def resize(self, resource_id: str, sku: str) -> MutationResult:
        current = self._resource(resource_id)
        if current is not None and current.get("sku") == sku:
            return _unchanged("resize", resource_id, current)
        return self._mutate(
            "POST",
            f"/resources/{resource_id}/actions/resize",
            {"sku": sku},
        )

    def schedule(self, resource_id: str, schedule: str) -> MutationResult:
        current = self._resource(resource_id)
        if current is not None and current.get("schedule") == schedule:
            return _unchanged("schedule", resource_id, current)
        return self._mutate(
            "POST",
            f"/resources/{resource_id}/actions/schedule",
            {"schedule": schedule},
        )

    def delete_unattached(self, resource_id: str) -> MutationResult:
        current = self._resource(resource_id)
        if current is None:
            return _unchanged("delete_unattached", resource_id, None)
        return self._mutate("POST", f"/resources/{resource_id}/actions/delete-unattached")

    def storage_lifecycle(self, resource_id: str, storage_class: str) -> MutationResult:
        current = self._resource(resource_id)
        if current is not None and current.get("storage_class") == storage_class:
            return _unchanged("storage_lifecycle", resource_id, current)
        return self._mutate(
            "POST",
            f"/resources/{resource_id}/actions/storage-lifecycle",
            {"storage_class": storage_class},
        )

    def rollback(self, action_id: str) -> MutationResult:
        return self._mutate("POST", f"/actions/{action_id}/rollback")

    def _resource(self, resource_id: str) -> dict | None:
        status, body = self._request("GET", f"{self.base_url}/resources/{resource_id}", None)
        if status == 404:
            return None
        if status >= 400:
            raise ApplyError(_detail(body, f"could not read resource {resource_id}"))
        if not isinstance(body, dict):
            raise ApplyError(f"could not read resource {resource_id}")
        return body

    def _mutate(self, method: str, path: str, body: dict | None = None) -> MutationResult:
        status, payload = self._request(method, f"{self.base_url}{path}", body)
        if status >= 400:
            raise ApplyError(_detail(payload, f"simulator {path} failed"))
        if not isinstance(payload, dict):
            raise ApplyError(f"simulator {path} returned an unexpected body")
        return MutationResult(
            action_id=str(payload["action_id"]),
            action=str(payload["action"]),
            resource_id=str(payload["resource_id"]),
            changed=True,
            resource=payload.get("resource") if isinstance(payload.get("resource"), dict) else None,
        )


def parse_plan_action(action: str) -> tuple[str, tuple[str, ...]]:
    """Parse one plan line into a verb and argument tuple. Does not mutate."""
    line = action.strip()
    if not line:
        raise ApplyError("plan action is blank")
    parts = line.split()
    verb = parts[0]
    if verb == "stop" and len(parts) == 2:
        return verb, (parts[1],)
    if verb == "start" and len(parts) == 2:
        return verb, (parts[1],)
    if verb == "resize" and len(parts) == 4 and parts[2] == "to":
        return verb, (parts[1], parts[3])
    if verb == "schedule" and len(parts) == 3:
        return verb, (parts[1], parts[2])
    if verb == "delete" and len(parts) == 2:
        return verb, (parts[1],)
    if verb == "transition" and len(parts) == 4 and parts[2] == "to":
        return verb, (parts[1], parts[3])
    raise ApplyError(f"unsupported plan action: {line}")


def apply_plan_action(adapter: CloudApplyAdapter, action: str) -> MutationResult:
    """Map one proposal plan line onto an adapter method."""
    verb, args = parse_plan_action(action)
    if verb == "stop":
        return adapter.stop(args[0])
    if verb == "start":
        return adapter.start(args[0])
    if verb == "resize":
        return adapter.resize(args[0], args[1])
    if verb == "schedule":
        return adapter.schedule(args[0], args[1])
    if verb == "delete":
        return adapter.delete_unattached(args[0])
    if verb == "transition":
        return adapter.storage_lifecycle(args[0], args[1])
    raise ApplyError(f"unsupported plan action: {action.strip()}")


def require_not_prohibited(session, proposal_id: str) -> None:
    """Re-evaluate live org policies immediately before mutate. Fail closed."""
    from app.repositories import prohibiting_policy

    prohibited = prohibiting_policy(session, proposal_id)
    if prohibited is not None:
        raise PolicyProhibitedError(prohibited, proposal_id)


def apply_action_to_run(
    session,
    execution_id: str,
    action: str,
    adapter: CloudApplyAdapter,
) -> MutationResult:
    """Apply one plan line and mark the run failed when the adapter errors.

    Re-checks prohibit policies immediately before each mutate. A queued run
    moves to running first. This does not mark the run succeeded; that belongs
    to applying the full plan.
    """
    from app.proposals import ExecutionStatus
    from app.repositories import ExecutionRunRepository

    runs = ExecutionRunRepository(session)
    run = runs.get(execution_id)
    if run is None:
        raise ApplyError(f"execution {execution_id} not found")
    require_not_prohibited(session, run.proposal_id)
    if run.status == ExecutionStatus.queued:
        runs.update_status(execution_id, ExecutionStatus.running)
    elif run.status != ExecutionStatus.running:
        raise ApplyError(f"execution {execution_id} is {run.status.value}")
    try:
        require_not_prohibited(session, run.proposal_id)
        return apply_plan_action(adapter, action)
    except ApplyError:
        runs.update_status(execution_id, ExecutionStatus.failed)
        raise


def apply_approved_plan(
    session,
    proposal_id: str,
    *,
    actor: str,
    adapter: CloudApplyAdapter | None = None,
):
    """Apply every plan step for an approved proposal to the simulator.

    Requires approval and a live policy pass at the execution boundary.
    Creates a queued ExecutionRun when one does not exist yet. A succeeded run
    is returned unchanged (idempotent re-entry). A failed or rolled_back run is
    refused. Adapter no-ops make individual steps safe to repeat; the normal
    path short-circuits when the run is already succeeded. A prohibit that
    appears after approve still blocks mutate.
    """
    from app.execution import ExecutionEventType
    from app.proposals import ApprovalStatus, ExecutionStatus
    from app.repositories import ExecutionRunRepository, ProposalRepository

    name = actor.strip()
    if not name:
        raise ApplyError("apply requires an actor")
    proposals = ProposalRepository(session)
    proposal = proposals.get(proposal_id)
    if proposal is None:
        raise ApplyError(f"proposal {proposal_id} not found")
    if proposal.approval_status != ApprovalStatus.approved:
        raise ApplyError(f"proposal {proposal_id} must be approved before apply")
    require_not_prohibited(session, proposal_id)

    runs = ExecutionRunRepository(session)
    run = runs.for_proposal(proposal_id)
    if run is None:
        proposals.begin_execution(proposal_id, actor=name)
        run = runs.for_proposal(proposal_id)
        if run is None:
            raise ApplyError(f"execution for {proposal_id} was not created")
    if run.status == ExecutionStatus.succeeded:
        return run
    if run.status in {ExecutionStatus.failed, ExecutionStatus.rolled_back}:
        raise ApplyError(f"execution {run.execution_id} is {run.status.value}")

    apply_adapter = adapter if adapter is not None else SimulatorApplyAdapter()
    action_ids: list[str] = []
    for action in run.plan_snapshot:
        result = apply_action_to_run(session, run.execution_id, action, apply_adapter)
        if result.changed and result.action_id:
            action_ids.append(result.action_id)
    runs.set_applied_action_ids(run.execution_id, action_ids)
    prior = runs.get(run.execution_id)
    from_status = ExecutionStatus.running if prior is None else prior.status
    finished = runs.update_status(run.execution_id, ExecutionStatus.succeeded)
    if finished is None:
        raise ApplyError(f"execution {run.execution_id} was not found after apply")
    runs.append_event(
        execution_id=finished.execution_id,
        proposal_id=finished.proposal_id,
        event_type=ExecutionEventType.apply,
        actor=name,
        reason="applied approved plan",
        from_status=from_status,
        to_status=ExecutionStatus.succeeded,
    )
    return finished


def rollback_execution(
    session,
    proposal_id: str,
    *,
    actor: str,
    reason: str,
    adapter: CloudApplyAdapter | None = None,
):
    """Reverse a succeeded apply through the simulator and audit who rolled it back.

    Prefers the stored simulator action ids in reverse order. When none were
    recorded, applies the stored rollback_plan lines instead. Marks the run
    rolled_back with the actor and reason.
    """
    from app.execution import ExecutionEventType
    from app.proposals import ExecutionStatus
    from app.repositories import ExecutionRunRepository

    name = actor.strip()
    why = reason.strip()
    if not name or not why:
        raise ApplyError("rollback requires an actor and a reason")
    runs = ExecutionRunRepository(session)
    run = runs.for_proposal(proposal_id)
    if run is None:
        raise ApplyError(f"execution for {proposal_id} not found")
    if run.status == ExecutionStatus.rolled_back:
        return run
    if run.status != ExecutionStatus.succeeded:
        raise ApplyError(f"execution {run.execution_id} must be succeeded to roll back")

    apply_adapter = adapter if adapter is not None else SimulatorApplyAdapter()
    try:
        if run.applied_action_ids:
            for action_id in reversed(run.applied_action_ids):
                apply_adapter.rollback(action_id)
        else:
            for action in run.rollback_plan:
                apply_plan_action(apply_adapter, action)
    except ApplyError:
        raise
    except Exception as exc:
        raise ApplyError(str(exc)) from exc

    finished = runs.update_status(
        run.execution_id,
        ExecutionStatus.rolled_back,
        rolled_back_by=name,
        rollback_reason=why,
    )
    if finished is None:
        raise ApplyError(f"execution {run.execution_id} was not found after rollback")
    runs.append_event(
        execution_id=finished.execution_id,
        proposal_id=finished.proposal_id,
        event_type=ExecutionEventType.rollback,
        actor=name,
        reason=why,
        from_status=ExecutionStatus.succeeded,
        to_status=ExecutionStatus.rolled_back,
    )
    return finished


def dry_run_execution(
    session,
    proposal_id: str,
    *,
    actor: str,
    adapter: CloudApplyAdapter | None = None,
):
    """Preview an approved plan: validate preconditions and write IaC, no mutate.

    Requires approval and a policy pass. Confirms each proposal resource still
    exists (API inventory, plus a simulator GET when an adapter is provided).
    Parses every plan line and writes the reviewable Terraform change. Does not
    create an ExecutionRun, does not change proposal execution_status, and does
    not call mutate APIs.
    """
    from pathlib import Path

    from app.execution import DryRunResult
    from app.proposals import ApprovalStatus
    from app.repositories import ProposalRepository, ResourceRepository
    from app.terraform_gen import generate_hcl, write_change

    name = actor.strip()
    if not name:
        raise ApplyError("dry-run requires an actor")
    proposals = ProposalRepository(session)
    proposal = proposals.get(proposal_id)
    if proposal is None:
        raise ApplyError(f"proposal {proposal_id} not found")
    if proposal.approval_status != ApprovalStatus.approved:
        raise ApplyError(f"proposal {proposal_id} must be approved before dry-run")
    require_not_prohibited(session, proposal_id)

    resources = ResourceRepository(session)
    for resource_id in proposal.resource_ids:
        if resources.get(resource_id) is None:
            raise ApplyError(f"precondition failed: resource {resource_id} is missing")
        if adapter is not None:
            current = _adapter_resource(adapter, resource_id)
            if current is None:
                raise ApplyError(
                    f"precondition failed: simulator resource {resource_id} is missing"
                )

    for action in proposal.proposed_actions:
        parse_plan_action(action)
    generate_hcl(proposal)
    artifact = write_change(proposal)
    if not Path(artifact.path).joinpath("main.tf").is_file():
        raise ApplyError(f"dry-run did not write IaC under {artifact.path}")

    return DryRunResult(
        proposal_id=proposal.proposal_id,
        actor=name,
        plan_snapshot=list(proposal.proposed_actions),
        rollback_plan=list(proposal.rollback_plan),
        preconditions=list(proposal.preconditions),
        artifact_path=artifact.path,
        artifact_hash=artifact.hash,
        artifact_created_at=artifact.created_at,
        dry_run=True,
    )


def _adapter_resource(adapter: CloudApplyAdapter, resource_id: str) -> dict | None:
    getter = getattr(adapter, "_resource", None)
    if callable(getter):
        return getter(resource_id)
    return None


def _unchanged(action: str, resource_id: str, resource: dict | None) -> MutationResult:
    return MutationResult(
        action_id="",
        action=action,
        resource_id=resource_id,
        changed=False,
        resource=resource,
    )


def _http_request(
    method: str, url: str, body: dict | None, token: str | None = None
) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            return response.status, json.loads(raw.decode())
    except HTTPError as exc:
        raw = exc.read()
        if not raw:
            return exc.code, str(exc.reason)
        try:
            return exc.code, json.loads(raw.decode())
        except json.JSONDecodeError:
            return exc.code, raw.decode()
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ApplyError(f"simulator request failed for {url}") from exc


def _detail(payload: object, fallback: str) -> str:
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        if isinstance(detail, str) and detail.strip():
            return detail
    if isinstance(payload, str) and payload.strip():
        return payload
    return fallback
