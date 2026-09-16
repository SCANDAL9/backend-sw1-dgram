"""0016_add_guide_session

Agrega la tabla `guide_session` para persistir el progreso y estado
del Agente de Onboarding Contextual (Spatial AI Guide).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guide_session",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("board_id", sa.String(length=36), sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column("completed_steps", JSONB, nullable=False, server_default="[]"),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_guide_session_board_id", "guide_session", ["board_id"])
    op.create_index("ix_guide_session_user_id", "guide_session", ["user_id"])
    op.create_index("ix_guide_session_session_token", "guide_session", ["session_token"])


def downgrade() -> None:
    op.drop_index("ix_guide_session_session_token", table_name="guide_session")
    op.drop_index("ix_guide_session_user_id", table_name="guide_session")
    op.drop_index("ix_guide_session_board_id", table_name="guide_session")
    op.drop_table("guide_session")
