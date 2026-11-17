"""Generate reviewable Terraform/HCL for MVP proposal actions.

Files are written under terraform/changes/<proposal_id>/main.tf. Each block
starts with a comment that names the proposal id. This does not run Terraform
and does not call AWS.
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.proposals import OptimizationProposal


def generate_hcl(proposal: OptimizationProposal) -> str:
    blocks = [
        f"# CloudSentry proposal: {proposal.proposal_id}",
        f"# Category: {proposal.category}",
        "# Review only. CloudSentry does not apply this file in v1.",
        "",
    ]
    for action in proposal.proposed_actions:
        blocks.append(_block_for_action(proposal.proposal_id, action))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def write_change(proposal: OptimizationProposal, *, root: Path | None = None) -> str:
    """Write main.tf for the proposal and return the relative artifact path."""
    base = root if root is not None else Path(get_settings().terraform_changes_dir)
    directory = base / _safe_name(proposal.proposal_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "main.tf"
    path.write_text(generate_hcl(proposal), encoding="utf-8")
    return path.as_posix()


def _block_for_action(proposal_id: str, action: str) -> str:
    line = action.strip()
    parts = line.split()
    verb = parts[0] if parts else ""
    if verb == "stop" and len(parts) == 2:
        return _stop(proposal_id, parts[1])
    if verb == "start" and len(parts) == 2:
        return _start(proposal_id, parts[1])
    if verb == "resize" and len(parts) == 4 and parts[2] == "to":
        return _resize(proposal_id, parts[1], parts[3])
    if verb == "schedule" and len(parts) == 3:
        return _schedule(proposal_id, parts[1], parts[2])
    if verb == "delete" and len(parts) == 2:
        return _delete(proposal_id, parts[1])
    if verb == "transition" and len(parts) == 4 and parts[2] == "to":
        return _transition(proposal_id, parts[1], parts[3])
    raise ValueError(f"unsupported plan action for terraform: {line}")


def _stop(proposal_id: str, resource_id: str) -> str:
    name = _resource_name(resource_id)
    return "\n".join(
        [
            f"# CloudSentry proposal: {proposal_id}",
            f"# Action: stop {resource_id}",
            f'resource "aws_ec2_instance_state" "{name}" {{',
            f'  instance_id = "{resource_id}"',
            '  state       = "stopped"',
            "}",
        ]
    )


def _start(proposal_id: str, resource_id: str) -> str:
    name = _resource_name(resource_id)
    return "\n".join(
        [
            f"# CloudSentry proposal: {proposal_id}",
            f"# Action: start {resource_id}",
            f'resource "aws_ec2_instance_state" "{name}" {{',
            f'  instance_id = "{resource_id}"',
            '  state       = "running"',
            "}",
        ]
    )


def _resize(proposal_id: str, resource_id: str, sku: str) -> str:
    name = _resource_name(resource_id)
    return "\n".join(
        [
            f"# CloudSentry proposal: {proposal_id}",
            f"# Action: resize {resource_id} to {sku}",
            f'resource "aws_instance" "{name}" {{',
            f'  instance_id   = "{resource_id}"',
            f'  instance_type = "{sku}"',
            "}",
        ]
    )


def _schedule(proposal_id: str, resource_id: str, schedule: str) -> str:
    name = _resource_name(resource_id)
    return "\n".join(
        [
            f"# CloudSentry proposal: {proposal_id}",
            f"# Action: schedule {resource_id} {schedule}",
            f'resource "aws_instance" "{name}" {{',
            f'  instance_id = "{resource_id}"',
            "  tags = {",
            f'    Schedule = "{schedule}"',
            "  }",
            "}",
        ]
    )


def _delete(proposal_id: str, resource_id: str) -> str:
    name = _resource_name(resource_id)
    return "\n".join(
        [
            f"# CloudSentry proposal: {proposal_id}",
            f"# Action: delete {resource_id}",
            f'# removed: aws_ebs_volume.{name} (id = "{resource_id}")',
        ]
    )


def _transition(proposal_id: str, resource_id: str, storage_class: str) -> str:
    name = _resource_name(resource_id)
    return "\n".join(
        [
            f"# CloudSentry proposal: {proposal_id}",
            f"# Action: transition {resource_id} to {storage_class}",
            f'resource "aws_s3_bucket_lifecycle_configuration" "{name}" {{',
            f'  bucket = "{resource_id}"',
            "  rule {",
            '    id     = "cloudsentry-transition"',
            '    status = "Enabled"',
            "    transition {",
            "      days          = 0",
            f'      storage_class = "{_s3_storage_class(storage_class)}"',
            "    }",
            "  }",
            "}",
        ]
    )


def _s3_storage_class(storage_class: str) -> str:
    if storage_class == "infrequent_access":
        return "STANDARD_IA"
    if storage_class == "standard":
        return "STANDARD"
    return storage_class.upper()


def _resource_name(resource_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in resource_id)


def _safe_name(proposal_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in proposal_id)
