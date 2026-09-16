"""0002_add_boards_created_by_and_citext

Añade:
  1. Extensión CITEXT en PostgreSQL y migra app_user.email a tipo CITEXT real.
  2. boards.created_by VARCHAR(36) FK nullable a app_user.id (ondelete SET NULL).
  3. Backfill de boards.created_by a partir de owner_id o usuario del sistema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT

# revision identifiers
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # 1. Extensión CITEXT
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")

    # 2. Migrar app_user.email a CITEXT
    op.execute("ALTER TABLE app_user ALTER COLUMN email TYPE citext;")

    # 3. Añadir created_by a boards
    op.add_column(
        "boards",
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_boards_created_by", "boards", ["created_by"])

    # 4. Backfill de boards.created_by
    op.execute(f"""
        UPDATE boards 
        SET created_by = owner_id 
        WHERE owner_id IN (SELECT id FROM app_user) AND created_by IS NULL;
    """)
    op.execute(f"""
        UPDATE boards 
        SET created_by = '{SYSTEM_USER_ID}' 
        WHERE created_by IS NULL;
    """)


def downgrade() -> None:
    op.drop_index("ix_boards_created_by", "boards")
    op.drop_column("boards", "created_by")
    op.execute("ALTER TABLE app_user ALTER COLUMN email TYPE varchar(255);")
