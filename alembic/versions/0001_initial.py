"""Начальная схема: пользователи, роли, клиенты, сделки, статусы, задачи, кастомные поля (EAV).

Revision ID: 0001
Revises:
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


def _enum(name: str, *values: str) -> sa.Enum:
    # как app.db.types.str_enum: VARCHAR без нативного ENUM
    return sa.Enum(*values, name=name, native_enum=False, length=32, validate_strings=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("permissions", JSONType, nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
    )
    op.create_index(op.f("ix_roles_code"), "roles", ["code"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("role_id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_users_role_id_roles"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role_id"), "users", ["role_id"])

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", _enum("client_type", "person", "company"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255)),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("address", sa.String(500)),
        sa.Column("notes", sa.Text()),
        sa.Column("owner_id", sa.Integer()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_clients_owner_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_index(op.f("ix_clients_name"), "clients", ["name"])
    op.create_index(op.f("ix_clients_email"), "clients", ["email"])
    op.create_index(op.f("ix_clients_phone"), "clients", ["phone"])
    op.create_index(op.f("ix_clients_owner_id"), "clients", ["owner_id"])

    op.create_table(
        "statuses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", _enum("status_entity", "deal"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("kind", _enum("status_kind", "open", "won", "lost"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statuses")),
        sa.UniqueConstraint("entity_type", "code", name="uq_statuses_entity_type_code"),
    )
    op.create_index(op.f("ix_statuses_entity_type"), "statuses", ["entity_type"])

    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("deal_date", sa.Date(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("status_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("responsible_id", sa.Integer()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("fk_deals_client_id_clients"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responsible_id"], ["users.id"], name=op.f("fk_deals_responsible_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["status_id"], ["statuses.id"], name=op.f("fk_deals_status_id_statuses"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deals")),
    )
    op.create_index(op.f("ix_deals_title"), "deals", ["title"])
    op.create_index(op.f("ix_deals_deal_date"), "deals", ["deal_date"])
    op.create_index(op.f("ix_deals_status_id"), "deals", ["status_id"])
    op.create_index(op.f("ix_deals_client_id"), "deals", ["client_id"])
    op.create_index(op.f("ix_deals_responsible_id"), "deals", ["responsible_id"])

    op.create_table(
        "custom_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", _enum("custom_entity", "client", "deal"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(150), nullable=False),
        sa.Column(
            "field_type",
            _enum(
                "custom_field_type", "text", "textarea", "integer", "decimal", "date", "datetime",
                "boolean", "select", "multiselect", "phone", "email", "url",
            ),
            nullable=False,
        ),
        sa.Column("options", JSONType, nullable=False),
        sa.Column("placeholder", sa.String(255)),
        sa.Column("help_text", sa.Text()),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("is_filterable", sa.Boolean(), nullable=False),
        sa.Column("show_in_list", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_fields")),
        sa.UniqueConstraint("entity_type", "code", name="uq_custom_fields_entity_type_code"),
    )
    op.create_index(op.f("ix_custom_fields_entity_type"), "custom_fields", ["entity_type"])

    op.create_table(
        "custom_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer()),
        sa.Column("deal_id", sa.Integer()),
        sa.Column("value_text", sa.Text()),
        sa.Column("value_number", sa.Numeric(20, 6)),
        sa.Column("value_date", sa.Date()),
        sa.Column("value_datetime", sa.DateTime(timezone=True)),
        sa.Column("value_bool", sa.Boolean()),
        sa.Column("value_json", JSONType),
        sa.CheckConstraint(
            "(client_id IS NOT NULL AND deal_id IS NULL) OR (client_id IS NULL AND deal_id IS NOT NULL)",
            name=op.f("ck_custom_values_exactly_one_owner"),
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("fk_custom_values_client_id_clients"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], name=op.f("fk_custom_values_deal_id_deals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["custom_fields.id"], name=op.f("fk_custom_values_field_id_custom_fields"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_values")),
        sa.UniqueConstraint("field_id", "client_id", name="uq_custom_values_field_client"),
        sa.UniqueConstraint("field_id", "deal_id", name="uq_custom_values_field_deal"),
    )
    op.create_index("ix_custom_values_client", "custom_values", ["client_id"])
    op.create_index("ix_custom_values_deal", "custom_values", ["deal_id"])
    op.create_index("ix_custom_values_field_number", "custom_values", ["field_id", "value_number"])
    op.create_index("ix_custom_values_field_date", "custom_values", ["field_id", "value_date"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", _enum("task_status", "todo", "in_progress", "done", "cancelled"), nullable=False),
        sa.Column("priority", _enum("task_priority", "low", "normal", "high", "urgent"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("assignee_id", sa.Integer()),
        sa.Column("creator_id", sa.Integer()),
        sa.Column("client_id", sa.Integer()),
        sa.Column("deal_id", sa.Integer()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], name=op.f("fk_tasks_assignee_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("fk_tasks_client_id_clients"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name=op.f("fk_tasks_creator_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], name=op.f("fk_tasks_deal_id_deals"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_assignee_status", "tasks", ["assignee_id", "status"])
    op.create_index(op.f("ix_tasks_due_at"), "tasks", ["due_at"])
    op.create_index(op.f("ix_tasks_client_id"), "tasks", ["client_id"])
    op.create_index(op.f("ix_tasks_deal_id"), "tasks", ["deal_id"])


def downgrade() -> None:
    for table in ("tasks", "custom_values", "custom_fields", "deals", "statuses", "clients", "users", "roles"):
        op.drop_table(table)
