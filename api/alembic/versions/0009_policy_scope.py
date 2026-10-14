"""Scope a policy to an environment and a resource type, and seed the defaults.

Revision ID: 0009_policy_scope
Revises: 0008_detection_run
Create Date: 2026-10-14
"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
import yaml

from alembic import op

revision: str = "0009_policy_scope"
down_revision: str | None = "0008_detection_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("policies", sa.Column("environment", sa.String(), nullable=True))
    op.add_column("policies", sa.Column("resource_type", sa.String(), nullable=True))
    connection = op.get_bind()
    statement = sa.text(
        "INSERT INTO policies (name, effect, actions, environment, resource_type) "
        "VALUES (:name, :effect, CAST(:actions AS jsonb), :environment, :resource_type) "
        "ON CONFLICT (name) DO UPDATE SET "
        "effect = EXCLUDED.effect, "
        "actions = EXCLUDED.actions, "
        "environment = EXCLUDED.environment, "
        "resource_type = EXCLUDED.resource_type"
    )
    for item in _defaults():
        connection.execute(
            statement,
            {
                "name": item["name"],
                "effect": item["effect"],
                "actions": json.dumps(item["actions"]),
                "environment": item.get("environment"),
                "resource_type": item.get("resource_type"),
            },
        )


def downgrade() -> None:
    op.drop_column("policies", "resource_type")
    op.drop_column("policies", "environment")


def _defaults() -> list[dict]:
    path = Path(__file__).resolve().parents[2] / "app" / "default_policies.yaml"
    loaded = yaml.safe_load(path.read_text())
    return list(loaded["policies"])
