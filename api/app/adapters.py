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
    ) -> None:
        self.base_url = (base_url or get_settings().simulator_base_url).rstrip("/")
        self._request = request or _http_request

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


def apply_plan_action(adapter: CloudApplyAdapter, action: str) -> MutationResult:
    """Map one proposal plan line onto an adapter method."""
    line = action.strip()
    if not line:
        raise ApplyError("plan action is blank")
    parts = line.split()
    verb = parts[0]
    if verb == "stop" and len(parts) == 2:
        return adapter.stop(parts[1])
    if verb == "start" and len(parts) == 2:
        return adapter.start(parts[1])
    if verb == "resize" and len(parts) == 4 and parts[2] == "to":
        return adapter.resize(parts[1], parts[3])
    if verb == "schedule" and len(parts) == 3:
        return adapter.schedule(parts[1], parts[2])
    if verb == "delete" and len(parts) == 2:
        return adapter.delete_unattached(parts[1])
    if verb == "transition" and len(parts) == 4 and parts[2] == "to":
        return adapter.storage_lifecycle(parts[1], parts[3])
    raise ApplyError(f"unsupported plan action: {line}")


def apply_action_to_run(
    session,
    execution_id: str,
    action: str,
    adapter: CloudApplyAdapter,
) -> MutationResult:
    """Apply one plan line and mark the run failed when the adapter errors.

    A queued run moves to running first. This does not mark the run succeeded;
    that belongs to applying the full plan.
    """
    from app.proposals import ExecutionStatus
    from app.repositories import ExecutionRunRepository

    runs = ExecutionRunRepository(session)
    run = runs.get(execution_id)
    if run is None:
        raise ApplyError(f"execution {execution_id} not found")
    if run.status == ExecutionStatus.queued:
        runs.update_status(execution_id, ExecutionStatus.running)
    elif run.status != ExecutionStatus.running:
        raise ApplyError(f"execution {execution_id} is {run.status.value}")
    try:
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

    Requires approval and a policy pass. Creates a queued ExecutionRun when
    one does not exist yet. A succeeded run is returned unchanged (idempotent
    re-entry). A failed or rolled_back run is refused. Adapter no-ops make
    individual steps safe to repeat; the normal path short-circuits when the
    run is already succeeded.
    """
    from app.proposals import ApprovalStatus, ExecutionStatus
    from app.repositories import (
        ExecutionRunRepository,
        ProposalRepository,
        _prohibited_execution,
    )

    name = actor.strip()
    if not name:
        raise ApplyError("apply requires an actor")
    proposals = ProposalRepository(session)
    proposal = proposals.get(proposal_id)
    if proposal is None:
        raise ApplyError(f"proposal {proposal_id} not found")
    if proposal.approval_status != ApprovalStatus.approved:
        raise ApplyError(f"proposal {proposal_id} must be approved before apply")
    prohibited = _prohibited_execution(
        session,
        proposal_id,
        ApprovalStatus.approved,
        ExecutionStatus.running,
    )
    if prohibited is not None:
        raise ApplyError(f"policy {prohibited} prohibits {proposal_id}")

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
    finished = runs.update_status(run.execution_id, ExecutionStatus.succeeded)
    if finished is None:
        raise ApplyError(f"execution {run.execution_id} was not found after apply")
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
    return finished


def _unchanged(action: str, resource_id: str, resource: dict | None) -> MutationResult:
    return MutationResult(
        action_id="",
        action=action,
        resource_id=resource_id,
        changed=False,
        resource=resource,
    )


def _http_request(method: str, url: str, body: dict | None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
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
