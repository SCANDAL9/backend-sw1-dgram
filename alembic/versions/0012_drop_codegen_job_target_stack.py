"""0012_drop_codegen_job_target_stack

Eliminación de la columna `target_stack` en `codegen_job`:
  - El sistema genera exclusivamente código en Spring Boot.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("codegen_job", "target_stack")


def downgrade() -> None:
    op.add_column(
        "codegen_job",
        sa.Column("target_stack", sa.String(50), nullable=False, server_default="spring_boot"),
    )
