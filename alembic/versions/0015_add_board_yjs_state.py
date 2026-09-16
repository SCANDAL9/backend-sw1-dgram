"""0015_add_board_yjs_state

Agrega el campo `yjs_state` (BYTEA / LargeBinary) a `boards`
para persistir instantáneas del estado binario del CRDT Yjs (Y.Doc).

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column("yjs_state", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("boards", "yjs_state")
