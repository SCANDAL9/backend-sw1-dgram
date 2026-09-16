"""0003_unify_user_table

Unifica la tabla de usuarios:
  1. Elimina la tabla temporal/legada `users` (sin auth).
  2. Renombra la tabla `app_user` a `users` (con todas las columnas de auth, CITEXT, avatar, etc.).
  3. Renombra los índices a `users`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Dropear tabla legada users si existe
    op.execute("DROP TABLE IF EXISTS users CASCADE;")

    # 2. Renombrar app_user a users
    op.execute("ALTER TABLE app_user RENAME TO users;")

    # 3. Renombrar índice de email
    op.execute("ALTER INDEX IF EXISTS uq_app_user_email RENAME TO uq_users_email;")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS uq_users_email RENAME TO uq_app_user_email;")
    op.execute("ALTER TABLE users RENAME TO app_user;")
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#6c7086"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
