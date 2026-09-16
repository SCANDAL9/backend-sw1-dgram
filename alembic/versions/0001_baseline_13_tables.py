"""0001_baseline_13_tables

Migración no-destructiva: añade las 13 tablas del esquema normalizado
y las columnas nuevas en boards (project_id, diagram_version).

NO elimina boards.diagram_snapshot ni la tabla users — se mantienen
como fallback durante el dual-write (Fases 2–3).
DROP ocurre en una migración futura (Fase 5).

Backfill incluido:
  1. Crea app_user sistema (id fijo '00000000-0000-0000-0000-000000000001')
  2. Inserta app_user por cada fila de users (username@local.invalid)
     usando ON CONFLICT DO NOTHING para idempotencia.

Revision ID: 0001
Revises: (baseline vacío)
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ENUM as PG_ENUM

# revision identifiers
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ─── Enums ──────────────────────────────────────────────────────────────
    # PG16 no soporta CREATE TYPE IF NOT EXISTS.
    # Usamos bloques DO con EXCEPTION WHEN duplicate_object para idempotencia.
    _enums = [
        ("project_role", "('owner', 'editor', 'viewer')"),
        ("stereotype_target", "('class', 'attribute', 'association')"),
        ("class_source", "('manual', 'archi_import', 'image_ocr')"),
        ("visibility_enum", "('public', 'private', 'protected', 'package')"),
        ("association_type", "('association', 'aggregation', 'composition', 'generalization', 'realization', 'dependency')"),
        ("actor_type_enum", "('user', 'ai')"),
        ("attachment_type", "('image', 'audio', 'video', 'document')"),
        ("action_status", "('success', 'failed')"),
        ("job_status", "('queued', 'running', 'success', 'failed')"),
    ]
    for enum_name, values in _enums:
        op.execute(sa.text(
            f"DO $$ BEGIN "
            f"  CREATE TYPE {enum_name} AS ENUM {values}; "
            f"EXCEPTION WHEN duplicate_object THEN NULL; "
            f"END $$"
        ))

    # ─── app_user ────────────────────────────────────────────────────────────
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        # email es CITEXT para login case-insensitive. Usamos Text + unique index.
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_app_user_email", "app_user", [sa.text("lower(email)")], unique=True)

    # ─── project ─────────────────────────────────────────────────────────────
    op.create_table(
        "project",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_project_owner_id", "project", ["owner_id"])

    # ─── project_member ───────────────────────────────────────────────────────
    op.create_table(
        "project_member",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", PG_ENUM("owner", "editor", "viewer", name="project_role", create_type=False), nullable=False, server_default="editor"),
        sa.Column("invited_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )

    # ─── package ──────────────────────────────────────────────────────────────
    op.create_table(
        "package",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_package_id", sa.String(36), sa.ForeignKey("package.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
    )
    op.create_index("ix_package_project_id", "package", ["project_id"])

    # ─── stereotype ───────────────────────────────────────────────────────────
    op.create_table(
        "stereotype",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("applies_to", PG_ENUM("class", "attribute", "association", name="stereotype_target", create_type=False), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
    )

    # ─── class_element ────────────────────────────────────────────────────────
    op.create_table(
        "class_element",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("package.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("stereotype_id", sa.String(36), sa.ForeignKey("stereotype.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_abstract", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("source", PG_ENUM("manual", "archi_import", "image_ocr", name="class_source", create_type=False), nullable=False, server_default="manual"),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_class_element_package_id", "class_element", ["package_id"])

    # ─── attribute ────────────────────────────────────────────────────────────
    op.create_table(
        "attribute",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("class_id", sa.String(36), sa.ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("data_type", sa.String(100), nullable=False, server_default="VARCHAR"),
        sa.Column("visibility", PG_ENUM("public", "private", "protected", "package", name="visibility_enum", create_type=False), nullable=False, server_default="public"),
        sa.Column("is_primary_key", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_foreign_key", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_derived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("default_value", sa.String(255), nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_attribute_class_id", "attribute", ["class_id"])

    # ─── association ──────────────────────────────────────────────────────────
    op.create_table(
        "association",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("source_class_id", sa.String(36), sa.ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_class_id", sa.String(36), sa.ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", PG_ENUM("association", "aggregation", "composition", "generalization", "realization", "dependency", name="association_type", create_type=False), nullable=False, server_default="association"),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("source_role", sa.String(100), nullable=True),
        sa.Column("target_role", sa.String(100), nullable=True),
        sa.Column("source_multiplicity", sa.String(20), nullable=True),
        sa.Column("target_multiplicity", sa.String(20), nullable=True),
    )

    # ─── association_class_link ───────────────────────────────────────────────
    op.create_table(
        "association_class_link",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("association_id", sa.String(36), sa.ForeignKey("association.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("class_id", sa.String(36), sa.ForeignKey("class_element.id", ondelete="RESTRICT"), nullable=False),
    )

    # ─── boards — nuevas columnas (no destructivo) ────────────────────────────
    # FK a project nullable: boards viejos no tienen proyecto asignado aún
    op.add_column("boards", sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="SET NULL"), nullable=True))
    # Optimistic locking: reemplaza CommandHandler.version en RAM
    op.add_column("boards", sa.Column("diagram_version", sa.Integer, nullable=False, server_default="0"))
    op.create_index("ix_boards_project_id", "boards", ["project_id"])
    op.create_index("ix_boards_updated_at", "boards", ["updated_at"])

    # ─── board_element ────────────────────────────────────────────────────────
    op.create_table(
        "board_element",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.String(36), sa.ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False),
        sa.Column("x", sa.Float, nullable=False, server_default="100"),
        sa.Column("y", sa.Float, nullable=False, server_default="100"),
        sa.Column("width", sa.Float, nullable=True),
        sa.Column("height", sa.Float, nullable=True),
        sa.UniqueConstraint("board_id", "class_id", name="uq_board_element_board_class"),
    )

    # ─── board_snapshots ──────────────────────────────────────────────────────
    op.create_table(
        "board_snapshots",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("board_id", "version", name="uq_board_snapshot_version"),
    )

    # ─── board_history ────────────────────────────────────────────────────────
    op.create_table(
        "board_history",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False, unique=True),
        sa.Column("command_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_type", PG_ENUM("user", "ai", name="actor_type_enum", create_type=False), nullable=False, server_default="user"),
        sa.Column("model_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_board_history_board_version", "board_history", ["board_id", "model_version"])
    op.create_index("ix_board_history_board_created", "board_history", ["board_id", "created_at"])

    # ─── chat_conversation ────────────────────────────────────────────────────
    op.create_table(
        "chat_conversation",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── chat_message ─────────────────────────────────────────────────────────
    op.create_table(
        "chat_message",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("chat_conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_type", PG_ENUM("user", "ai", name="actor_type_enum", create_type=False), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── chat_attachment ──────────────────────────────────────────────────────
    op.create_table(
        "chat_attachment",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("chat_message_id", sa.String(36), sa.ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", PG_ENUM("image", "audio", "video", "document", name="attachment_type", create_type=False), nullable=False),
        sa.Column("storage_url", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )

    # ─── ai_action ────────────────────────────────────────────────────────────
    op.create_table(
        "ai_action",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("chat_message_id", sa.String(36), sa.ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("board_history_id", sa.String(36), sa.ForeignKey("board_history.id", ondelete="SET NULL"), nullable=True),
        sa.Column("function_name", sa.String(100), nullable=False),
        sa.Column("function_arguments", JSONB, nullable=True),
        sa.Column("status", PG_ENUM("success", "failed", name="action_status", create_type=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── audit_logs ───────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_project_created", "audit_logs", ["project_id", "created_at"])

    # ─── codegen_job ──────────────────────────────────────────────────────────
    op.create_table(
        "codegen_job",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_stack", sa.String(50), nullable=False, server_default="spring_boot"),
        sa.Column("status", PG_ENUM("queued", "running", "success", "failed", name="job_status", create_type=False), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ─── Backfill: usuario sistema ────────────────────────────────────────────
    # ID fijo para que el backfill de boards.owner_id="system" tenga FK válida
    op.execute(f"""
        INSERT INTO app_user (id, full_name, email, password_hash, created_at)
        VALUES (
            '{SYSTEM_USER_ID}',
            'Sistema dgram',
            'system@dgram.internal',
            NULL,
            NOW()
        )
        ON CONFLICT DO NOTHING
    """)

    # ─── Backfill: users → app_user ───────────────────────────────────────────
    # username no es un email real → se convierte en username@local.invalid
    # display_name → full_name
    # ON CONFLICT DO NOTHING: idempotente si la migración se corre dos veces
    op.execute("""
        INSERT INTO app_user (id, full_name, email, password_hash, created_at)
        SELECT
            id,
            display_name,
            username || '@local.invalid',
            NULL,
            created_at
        FROM users
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # Orden inverso respetando FKs
    op.drop_table("codegen_job")
    op.drop_table("audit_logs")
    op.drop_table("ai_action")
    op.drop_table("chat_attachment")
    op.drop_table("chat_message")
    op.drop_table("chat_conversation")
    op.drop_index("ix_board_history_board_created", "board_history")
    op.drop_index("ix_board_history_board_version", "board_history")
    op.drop_table("board_history")
    op.drop_table("board_snapshots")
    op.drop_table("board_element")
    op.drop_index("ix_boards_updated_at", "boards")
    op.drop_index("ix_boards_project_id", "boards")
    op.drop_column("boards", "diagram_version")
    op.drop_column("boards", "project_id")
    op.drop_table("association_class_link")
    op.drop_table("association")
    op.drop_index("ix_attribute_class_id", "attribute")
    op.drop_table("attribute")
    op.drop_index("ix_class_element_package_id", "class_element")
    op.drop_table("class_element")
    op.drop_table("stereotype")
    op.drop_index("ix_package_project_id", "package")
    op.drop_table("package")
    op.drop_table("project_member")
    op.drop_index("ix_project_owner_id", "project")
    op.drop_table("project")
    op.drop_index("uq_app_user_email", "app_user")
    op.drop_table("app_user")
    # Enums
    for enum_name in [
        "project_role", "stereotype_target", "class_source",
        "visibility_enum", "association_type", "actor_type_enum",
        "attachment_type", "action_status", "job_status",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
