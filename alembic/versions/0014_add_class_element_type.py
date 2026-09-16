"""0014_add_class_element_type

Agrega el campo `element_type` (enum `class_element_type`) a `class_element`
para soportar clasificadores UML completos (class, abstract_class, interface, enumeration, datatype).

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

# revision identifiers
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

ELEMENT_TYPES = ("class", "abstract_class", "interface", "enumeration", "datatype")


def upgrade() -> None:
    classifier_enum = PG_ENUM(*ELEMENT_TYPES, name="class_element_type")
    classifier_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "class_element",
        sa.Column(
            "element_type",
            classifier_enum,
            nullable=False,
            server_default="class",
        ),
    )


def downgrade() -> None:
    op.drop_column("class_element", "element_type")
    classifier_enum = PG_ENUM(*ELEMENT_TYPES, name="class_element_type")
    classifier_enum.drop(op.get_bind(), checkfirst=True)
