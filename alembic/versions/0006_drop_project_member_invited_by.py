"""0006_drop_project_member_invited_by

Eliminación de la columna `invited_by` en `project_member`:
  - Solo el propietario del proyecto puede invitar miembros.
  - Se elimina la columna y su FK hacia `users.id`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("project_member", "invited_by")


def downgrade() -> None:
    op.add_column(
        "project_member",
        sa.Column("invited_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
