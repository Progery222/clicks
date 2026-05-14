"""ip auth lockout

Revision ID: 20260213_0002
Revises: 20250514_0001
Create Date: 2026-02-13

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260213_0002"
down_revision: Union[str, None] = "20250514_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ip_auth_lockout",
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("admin_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("api_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("ip"),
    )


def downgrade() -> None:
    op.drop_table("ip_auth_lockout")
