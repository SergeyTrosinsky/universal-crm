"""Шаблоны сделок: наборы дополнительных полей, выбираемые при создании сделки.

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deal_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_templates")),
    )
    for table in ("custom_fields", "deals"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("template_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                op.f(f"fk_{table}_template_id_deal_templates"),
                "deal_templates", ["template_id"], ["id"], ondelete="SET NULL",
            )
            batch.create_index(op.f(f"ix_{table}_template_id"), ["template_id"])


def downgrade() -> None:
    for table in ("deals", "custom_fields"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(op.f(f"ix_{table}_template_id"))
            batch.drop_constraint(op.f(f"fk_{table}_template_id_deal_templates"), type_="foreignkey")
            batch.drop_column("template_id")
    op.drop_table("deal_templates")
