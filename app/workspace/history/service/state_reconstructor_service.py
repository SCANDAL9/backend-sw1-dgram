"""
state_reconstructor_service.py — Reconstruye el estado del diagrama a partir de las tablas normalizadas.

Tablas consultadas:
  - boards (project_id, diagram_version)
  - class_element JOIN board_element (posiciones x, y, width, height)
  - attribute (columnas/atributos ordenados por order_index)
  - association (relaciones/asociaciones entre clases del board)
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.uml_entity import (
    ClassElement, Attribute, Association, AssociationType, AssociationClassLink, Package
)
from app.modeling.diagram.entity.board_normalized_entity import BoardElement, BoardSnapshot


def coerce_uuid(val: str | None) -> str:
    if not val:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(val))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"dgram.entity.{val}"))


def parse_assoc_type(raw_type: str | None) -> AssociationType:
    if not raw_type:
        return AssociationType.association
    val = str(raw_type).lower().strip()
    mapping = {
        "1:1": AssociationType.association,
        "1:n": AssociationType.association,
        "n:m": AssociationType.association,
        "association": AssociationType.association,
        "aggregation": AssociationType.aggregation,
        "composition": AssociationType.composition,
        "generalization": AssociationType.generalization,
        "inheritance": AssociationType.generalization,
        "realization": AssociationType.realization,
        "dependency": AssociationType.dependency,
    }
    return mapping.get(val, AssociationType.association)


async def get_normalized_board_state(db: AsyncSession, board_id: str) -> dict | None:
    board = await db.get(Board, board_id)
    if not board:
        return None

    if not board.project_id:
        snap_res = await db.execute(
            select(BoardSnapshot)
            .where(BoardSnapshot.board_id == board_id)
            .order_by(BoardSnapshot.version.desc())
            .limit(1)
        )
        snap = snap_res.scalar_one_or_none()
        if hasattr(snap, "__await__"):
            snap = await snap
        if snap and hasattr(snap, "snapshot") and isinstance(snap.snapshot, dict):
            return snap.snapshot
        if snap and hasattr(snap, "state") and isinstance(snap.state, dict):
            return snap.state
        return None

    packages_list = []
    if board.project_id:
        pkg_stmt = select(Package).where(Package.project_id == board.project_id)
        pkg_res = await db.execute(pkg_stmt)
        for p in pkg_res.scalars().all():
            packages_list.append({
                "id": p.id,
                "name": p.name,
                "project_id": p.project_id,
            })

    elem_stmt = (
        select(BoardElement, ClassElement)
        .join(ClassElement, BoardElement.class_id == ClassElement.id)
        .where(BoardElement.board_id == board_id)
    )
    elem_res = await db.execute(elem_stmt)
    elem_rows = elem_res.all()

    if not elem_rows:
        return {
            "version": board.diagram_version or 1,
            "entities": [],
            "relations": [],
            "classes": [],
            "associations": [],
            "packages": packages_list,
        }

    entities = []
    classes = []
    class_ids = set()

    for be, ce in elem_rows:
        class_ids.add(ce.id)

        attr_stmt = select(Attribute).where(Attribute.class_id == ce.id).order_by(Attribute.order_index)
        attr_res = await db.execute(attr_stmt)
        attrs = attr_res.scalars().all()

        columns = []
        for a in attrs:
            dt = a.data_type or "VARCHAR"
            is_pk = bool(a.is_pkey)
            is_fk = bool(a.is_fkey)
            is_null = not is_pk and (a.visibility.value if hasattr(a.visibility, "value") else str(a.visibility)) != "public"
            columns.append({
                "name": a.name,
                "type": dt,
                "is_primary": is_pk,
                "is_foreign": is_fk,
                "nullable": is_null,
            })

        attributes_list = [
            {
                "id": a.id,
                "name": a.name,
                "data_type": a.data_type,
                "type": a.data_type,
                "visibility": a.visibility.value if hasattr(a.visibility, "value") else str(a.visibility),
                "is_pkey": bool(a.is_pkey),
                "is_fkey": bool(a.is_fkey),
                "pk": bool(a.is_pkey),
                "fk": bool(a.is_fkey),
                "order_index": a.order_index,
            }
            for a in attrs
        ]

        pos_x = getattr(be, "x", getattr(be, "pos_x", 100.0))
        pos_y = getattr(be, "y", getattr(be, "pos_y", 100.0))
        w = getattr(be, "width", None)
        h = getattr(be, "height", None)

        entities.append({
            "id": ce.id,
            "name": ce.name,
            "position": {"x": float(pos_x), "y": float(pos_y)},
            "width": float(w) if w is not None else None,
            "height": float(h) if h is not None else None,
            "columns": columns,
            "attributes": attributes_list,
            "package_id": ce.package_id,
            "element_type": ce.element_type.value if hasattr(ce.element_type, "value") else str(ce.element_type),
            "is_abstract": bool(ce.is_abstract),
            "is_visible": bool(getattr(ce, "is_visible", True) if getattr(ce, "is_visible", True) is not None else True),
        })

        classes.append({
            "id": ce.id,
            "name": ce.name,
            "package_id": ce.package_id,
            "is_abstract": bool(ce.is_abstract),
            "is_visible": bool(getattr(ce, "is_visible", True) if getattr(ce, "is_visible", True) is not None else True),
            "element_type": ce.element_type.value if hasattr(ce.element_type, "value") else str(ce.element_type),
            "attributes": attributes_list,
        })

    relations = []
    associations = []

    if class_ids:
        assoc_stmt = select(Association).where(
            Association.source_class_id.in_(class_ids),
            Association.target_class_id.in_(class_ids),
        )
        assoc_res = await db.execute(assoc_stmt)
        assoc_rows = assoc_res.scalars().all()

        links = {}
        if assoc_rows:
            link_stmt = select(AssociationClassLink).where(
                AssociationClassLink.association_id.in_([a.id for a in assoc_rows])
            )
            link_res = await db.execute(link_stmt)
            links = {l.association_id: l.class_id for l in link_res.scalars().all()}

        for asc in assoc_rows:
            assoc_class_link_id = links.get(asc.id)
            card_map = {
                "one_to_one": "1:1",
                "one_to_many": "1:n",
                "many_to_many": "n:m",
                "1:1": "1:1",
                "1:n": "1:n",
                "n:m": "n:m",
            }
            card_val = getattr(asc, "cardinality", getattr(asc, "target_multiplicity", "1:n"))
            rel_type = card_map.get(str(card_val).lower(), "1:n")
            asc_type = asc.type.value if hasattr(asc.type, "value") else str(asc.type)
            relations.append({
                "id": asc.id,
                "source_id": asc.source_class_id,
                "target_id": asc.target_class_id,
                "type": asc_type,
                "cardinality": rel_type,
                "name": asc.name,
                "source_role": asc.source_role,
                "target_role": asc.target_role,
                "source_multiplicity": asc.source_multiplicity,
                "target_multiplicity": asc.target_multiplicity,
                "association_class_id": assoc_class_link_id,
                "associationClassId": assoc_class_link_id,
            })

            associations.append({
                "id": asc.id,
                "name": asc.name,
                "type": asc.type.value if hasattr(asc.type, "value") else str(asc.type),
                "source_class_id": asc.source_class_id,
                "target_class_id": asc.target_class_id,
                "source_role": asc.source_role,
                "target_role": asc.target_role,
                "source_cardinality": getattr(asc, "source_cardinality", asc.source_multiplicity),
                "target_cardinality": getattr(asc, "target_cardinality", asc.target_multiplicity),
                "cardinality": getattr(asc, "cardinality", asc.target_multiplicity),
                "is_association_class": bool(getattr(asc, "is_association_class", False) or assoc_class_link_id is not None),
                "association_class_id": assoc_class_link_id,
                "associationClassId": assoc_class_link_id,
            })

    return {
        "version": board.diagram_version or 1,
        "entities": entities,
        "relations": relations,
        "classes": classes,
        "associations": associations,
        "packages": packages_list,
    }
