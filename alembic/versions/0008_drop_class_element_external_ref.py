"""0008_drop_class_element_external_ref

Eliminación de la columna `external_ref` en `class_element`:
  - Campo no utilizado para deduplicación externa de XMLs.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("class_element", "external_ref")


def downgrade() -> None:
    op.add_column(
        "class_element",
        sa.Column("external_ref", sa.String(255), nullable=True),
    )
