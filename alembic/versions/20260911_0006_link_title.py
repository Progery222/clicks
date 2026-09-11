"""title on links (display name)

Revision ID: 20260911_0006
Revises: 20260708_0005
Create Date: 2026-09-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0006"
down_revision: Union[str, None] = "20260708_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("links", sa.Column("title", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("links", "title")
