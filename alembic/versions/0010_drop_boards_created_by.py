"""0010_drop_boards_created_by

Eliminación de la columna `created_by` en `boards`:
  - `owner_id` es el campo único autoritativo de pertenencia del tablero.
  - Se elimina la columna redundante `created_by` y su índice `ix_boards_created_by`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_boards_created_by", "boards")
    op.drop_column("boards", "created_by")


def downgrade() -> None:
    op.add_column(
        "boards",
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_boards_created_by", "boards", ["created_by"])
