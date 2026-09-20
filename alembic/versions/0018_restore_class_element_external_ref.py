"""0018_restore_class_element_external_ref

Restaura la columna `external_ref` en `class_element` para soporte de deduplicación
y trazabilidad bidireccional de identificadores externos de Enterprise Architect (XMI 2.1).

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "class_element",
        sa.Column("external_ref", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_class_element_package_external_ref",
        "class_element",
        ["package_id", "external_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_class_element_package_external_ref", "class_element")
    op.drop_column("class_element", "external_ref")
