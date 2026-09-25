"""
Schema Mapper — Mapper utility for XMI and schema entities.
"""
from typing import Any
from app.modeling.diagram.entity.uml_entity import ClassElement, Attribute, Association


class SchemaMapper:
    @staticmethod
    def class_to_dict(c: ClassElement, attrs: list[Attribute], pos: dict[str, float]) -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "package_id": getattr(c, "package_id", None),
            "element_type": c.element_type.value if hasattr(c.element_type, "value") else str(c.element_type),
            "is_abstract": c.is_abstract,
            "is_visible": getattr(c, "is_visible", True),
            "external_ref": getattr(c, "external_ref", None),
            "attributes": [
                {
                    "id": a.id,
                    "name": a.name,
                    "data_type": a.data_type,
                    "visibility": a.visibility.value if hasattr(a.visibility, "value") else str(a.visibility),
                    "is_pkey": a.is_pkey,
                }
                for a in attrs
            ],
            "position": pos,
        }

    @staticmethod
    def association_to_dict(a: Association) -> dict[str, Any]:
        return {
            "id": a.id,
            "sourceId": a.source_class_id,
            "targetId": a.target_class_id,
            "type": a.type.value if hasattr(a.type, "value") else str(a.type),
            "name": a.name,
            "source_role": a.source_role,
            "target_role": a.target_role,
            "source_multiplicity": a.source_multiplicity,
            "target_multiplicity": a.target_multiplicity,
        }
