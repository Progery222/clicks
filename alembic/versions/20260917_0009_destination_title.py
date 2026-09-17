"""destination_title on links

Revision ID: 20260917_0009
Revises: 20260911_0008
Create Date: 2026-09-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0009"
down_revision: Union[str, None] = "20260911_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("links", sa.Column("destination_title", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("links", "destination_title")
