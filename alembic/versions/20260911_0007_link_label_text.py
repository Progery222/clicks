"""label: String(255) -> Text for multiple accounts

Revision ID: 20260911_0007
Revises: 20260911_0006
Create Date: 2026-09-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0007"
down_revision: Union[str, None] = "20260911_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "links",
        "label",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "links",
        "label",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
