"""profiles and link profile_id, platform

Revision ID: 20260213_0003
Revises: 20260213_0002
Create Date: 2026-02-13

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260213_0003"
down_revision: Union[str, None] = "20260213_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("links", sa.Column("platform", sa.String(length=20), nullable=True))
    op.add_column("links", sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_links_platform"), "links", ["platform"], unique=False)
    op.create_index(op.f("ix_links_profile_id"), "links", ["profile_id"], unique=False)
    op.create_foreign_key(
        "fk_links_profile_id_profiles",
        "links",
        "profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Заполнить platform из label для существующих ссылок
    from app.platforms import detect_platform_from_text

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, label FROM links")).fetchall()
    for row in rows:
        pid = detect_platform_from_text(row.label)
        if pid:
            conn.execute(
                sa.text("UPDATE links SET platform = :p WHERE id = :id"),
                {"p": pid, "id": row.id},
            )


def downgrade() -> None:
    op.drop_constraint("fk_links_profile_id_profiles", "links", type_="foreignkey")
    op.drop_index(op.f("ix_links_profile_id"), table_name="links")
    op.drop_index(op.f("ix_links_platform"), table_name="links")
    op.drop_column("links", "profile_id")
    op.drop_column("links", "platform")
    op.drop_table("profiles")
