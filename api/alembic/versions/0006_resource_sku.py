"""Store the simulator SKU used by rightsizing.

Revision ID: 0006_resource_sku
Revises: 0005_resource_present
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_resource_sku"
down_revision: str | None = "0005_resource_present"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("sku", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("resources", "sku")
