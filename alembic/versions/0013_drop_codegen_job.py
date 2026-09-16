"""0013_drop_codegen_job

Eliminación de la tabla `codegen_job` y enum `job_status`:
  - La generación de código en Spring Boot se ejecuta de manera síncrona en memoria.
  - Se elimina la persistencia de jobs y su enum asociado.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

# revision identifiers
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("codegen_job")
    job_status_enum = PG_ENUM("queued", "running", "success", "failed", name="job_status")
    job_status_enum.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    job_status_enum = PG_ENUM("queued", "running", "success", "failed", name="job_status")
    job_status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "codegen_job",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", job_status_enum, nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
