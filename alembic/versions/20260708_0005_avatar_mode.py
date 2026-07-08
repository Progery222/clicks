"""account_avatar_mode on links

Revision ID: 20260708_0005
Revises: 20260708_0004
Create Date: 2026-07-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260708_0005"
down_revision: Union[str, None] = "20260708_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "links",
        sa.Column(
            "account_avatar_mode",
            sa.String(16),
            nullable=False,
            server_default="auto",
        ),
    )


def downgrade() -> None:
    op.drop_column("links", "account_avatar_mode")
