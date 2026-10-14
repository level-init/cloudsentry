"""Store the simulator storage class used by lifecycle detection.

Revision ID: 0007_resource_storage_class
Revises: 0006_resource_sku
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_resource_storage_class"
down_revision: str | None = "0006_resource_sku"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("storage_class", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("resources", "storage_class")
