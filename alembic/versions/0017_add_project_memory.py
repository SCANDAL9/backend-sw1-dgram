"""0017_add_project_memory

Agrega la tabla `project_memory` para persistir el Memory Bank de directivas,
convenciones arquitectónicas y reglas de negocio vinculadas a cada proyecto.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_memory",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="convention"),
        sa.Column("directive", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_project_memory_project_id", "project_memory", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_memory_project_id", table_name="project_memory")
    op.drop_table("project_memory")
