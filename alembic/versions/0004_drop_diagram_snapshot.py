"""0004_drop_diagram_snapshot

Fase 5 de la migración:
  - Elimina la columna obsoleta `boards.diagram_snapshot`.
  - A partir de este punto, el estado del diagrama se lee y persiste
    exclusivamente a través de las tablas relacionales normalizadas
    (class_element, attribute, association, board_element) y la caché JSONB (board_snapshots).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dropear columna obsoleta diagram_snapshot de boards
    op.drop_column("boards", "diagram_snapshot")


def downgrade() -> None:
    op.add_column("boards", sa.Column("diagram_snapshot", sa.Text(), nullable=True))
