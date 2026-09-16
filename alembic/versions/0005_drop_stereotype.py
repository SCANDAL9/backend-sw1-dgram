"""0005_drop_stereotype

Eliminación de la tabla stereotype:
  - Elimina la columna `stereotype_id` y su FK en `class_element`.
  - Elimina la tabla física `stereotype`.
  - Elimina el enum `stereotype_target`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

# revision identifiers
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Eliminar FK y columna stereotype_id de class_element
    op.drop_column("class_element", "stereotype_id")

    # 2. Eliminar tabla stereotype
    op.drop_table("stereotype")

    # 3. Eliminar enum stereotype_target
    stereotype_target_enum = PG_ENUM("class", "attribute", "association", name="stereotype_target")
    stereotype_target_enum.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # 1. Recrear enum stereotype_target
    stereotype_target_enum = PG_ENUM("class", "attribute", "association", name="stereotype_target")
    stereotype_target_enum.create(op.get_bind(), checkfirst=True)

    # 2. Recrear tabla stereotype
    op.create_table(
        "stereotype",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("applies_to", stereotype_target_enum, nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
    )

    # 3. Recrear columna stereotype_id en class_element
    op.add_column(
        "class_element",
        sa.Column("stereotype_id", sa.String(36), sa.ForeignKey("stereotype.id", ondelete="SET NULL"), nullable=True),
    )
