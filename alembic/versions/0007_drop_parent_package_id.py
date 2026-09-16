"""0007_drop_parent_package_id

Eliminación de la columna `parent_package_id` en `package`:
  - Los paquetes pasan de jerarquía en árbol a estructura plana (proyecto -> paquetes).
  - Se elimina la columna autorreferencial y su FK en cascada.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("package", "parent_package_id")


def downgrade() -> None:
    op.add_column(
        "package",
        sa.Column("parent_package_id", sa.String(36), sa.ForeignKey("package.id", ondelete="CASCADE"), nullable=True),
    )
