"""0009_rename_attribute_pk_fk_columns

Renombrar columnas en `attribute`:
  - `is_primary_key` -> `is_pkey`
  - `is_foreign_key` -> `is_fkey`

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("attribute", "is_primary_key", new_column_name="is_pkey")
    op.alter_column("attribute", "is_foreign_key", new_column_name="is_fkey")


def downgrade() -> None:
    op.alter_column("attribute", "is_pkey", new_column_name="is_primary_key")
    op.alter_column("attribute", "is_fkey", new_column_name="is_foreign_key")
