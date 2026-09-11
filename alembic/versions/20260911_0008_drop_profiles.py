"""drop profiles table and links.profile_id

Revision ID: 20260911_0008
Revises: 20260911_0007
Create Date: 2026-09-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_0008"
down_revision: Union[str, None] = "20260911_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("fk_links_profile_id_profiles", "links", type_="foreignkey")
    op.drop_index(op.f("ix_links_profile_id"), table_name="links")
    op.drop_column("links", "profile_id")
    op.drop_table("profiles")


def downgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False, server_default="#6366f1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("links", sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_links_profile_id"), "links", ["profile_id"], unique=False)
    op.create_foreign_key(
        "fk_links_profile_id_profiles",
        "links",
        "profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
