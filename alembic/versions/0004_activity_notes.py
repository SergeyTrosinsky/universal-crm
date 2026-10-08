"""История изменений (activity_events) и заметки (notes) в карточках клиентов и сделок.

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")
ONE_OWNER = "(client_id IS NOT NULL AND deal_id IS NULL) OR (client_id IS NULL AND deal_id IS NOT NULL)"


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("client_id", sa.Integer()),
        sa.Column("deal_id", sa.Integer()),
        sa.Column("actor_id", sa.Integer()),
        sa.Column("actor_name", sa.String(255)),
        sa.Column("changes", JSONType),
        sa.CheckConstraint(ONE_OWNER, name=op.f("ck_activity_events_exactly_one_owner")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("fk_activity_events_client_id_clients"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], name=op.f("fk_activity_events_deal_id_deals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_activity_events_actor_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_events")),
    )
    op.create_index("ix_activity_events_client", "activity_events", ["client_id", "created_at"])
    op.create_index("ix_activity_events_deal", "activity_events", ["deal_id", "created_at"])

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Integer()),
        sa.Column("deal_id", sa.Integer()),
        sa.Column("author_id", sa.Integer()),
        sa.Column("author_name", sa.String(255)),
        sa.CheckConstraint(ONE_OWNER, name=op.f("ck_notes_exactly_one_owner")),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("fk_notes_client_id_clients"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], name=op.f("fk_notes_deal_id_deals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_notes_author_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
    )
    op.create_index("ix_notes_client", "notes", ["client_id", "created_at"])
    op.create_index("ix_notes_deal", "notes", ["deal_id", "created_at"])


def downgrade() -> None:
    op.drop_table("notes")
    op.drop_table("activity_events")
