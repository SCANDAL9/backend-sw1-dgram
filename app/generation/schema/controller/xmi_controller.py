"""
xmi_controller.py — Endpoints de Importación y Exportación XMI 2.1 (Enterprise Architect).
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.uml_entity import Package, ClassElement, Attribute, Association, ClassifierType, VisibilityEnum, AssociationType
from app.modeling.diagram.entity.board_normalized_entity import BoardElement
from app.modeling.diagram.service.relational_mutator_service import ensure_project_and_package
from app.generation.schema.service.xmi_service import XmiExporter, XmiImporter
from app.generation.schema.mapper.schema_mapper import SchemaMapper

router = APIRouter()


@router.get("/boards/{board_id}/export/xmi")
async def export_board_xmi(board_id: str, db: AsyncSession = Depends(get_db)):
    """Exporta el diagrama y modelo del tablero a formato XMI 2.1 compatible con Enterprise Architect."""
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    project_id, package_id = await ensure_project_and_package(db, board)
    await db.commit()

    # Obtener elementos en el tablero
    be_stmt = select(BoardElement).where(BoardElement.board_id == board_id)
    be_res = await db.execute(be_stmt)
    board_elements = be_res.scalars().all()

    board_element_map = {
        be.class_id: {"x": be.x, "y": be.y, "w": be.width or 220.0, "h": be.height or 160.0}
        for be in board_elements
    }

    # Obtener clases asociadas al proyecto/tablero
    class_ids = list(board_element_map.keys())
    if not class_ids:
        cls_all_stmt = select(ClassElement).where(ClassElement.package_id == package_id)
        cls_all_res = await db.execute(cls_all_stmt)
        classes_db = cls_all_res.scalars().all()
    else:
        cls_stmt = select(ClassElement).where(ClassElement.id.in_(class_ids))
        cls_res = await db.execute(cls_stmt)
        classes_db = cls_res.scalars().all()

    classes_payload = []
    for c in classes_db:
        attr_stmt = select(Attribute).where(Attribute.class_id == c.id).order_by(Attribute.order_index)
        attr_res = await db.execute(attr_stmt)
        attrs = attr_res.scalars().all()

        pos = board_element_map.get(c.id, {"x": 100.0, "y": 100.0})
        classes_payload.append(SchemaMapper.class_to_dict(c, attrs, pos))

    # Obtener asociaciones
    if classes_payload:
        c_ids = [c["id"] for c in classes_payload]
        assoc_stmt = select(Association).where(
            Association.source_class_id.in_(c_ids),
            Association.target_class_id.in_(c_ids),
        )
        assoc_res = await db.execute(assoc_stmt)
        associations_db = assoc_res.scalars().all()
        assoc_payload = [SchemaMapper.association_to_dict(a) for a in associations_db]
    else:
        assoc_payload = []

    exporter = XmiExporter()
    xml_content = exporter.export_board(
        project_name=board.name,
        board_name=board.name,
        classes=classes_payload,
        associations=assoc_payload,
        board_elements=board_element_map,
    )

    filename = f"{board.name.replace(' ', '_')}.xmi"
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/boards/{board_id}/import/xmi")
async def import_board_xmi(
    board_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Importa un archivo XMI/XML de Enterprise Architect al tablero actual."""
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    project_id, package_id = await ensure_project_and_package(db, board)

    try:
        content_bytes = await file.read()
        xml_str = content_bytes.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo XML: {str(e)}")

    importer = XmiImporter()
    try:
        parsed = importer.parse(xml_str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Error al procesar XMI: {str(e)}")

    imported_classes = []
    class_id_map = {}

    for cls in parsed.get("classes", []):
        c_name = cls.get("name")
        if not c_name:
            continue

        c_type_str = cls.get("element_type", "class").lower()
        c_type = ClassifierType.interface if c_type_str == "interface" else ClassifierType.class_

        class_elem = ClassElement(
            package_id=package_id,
            name=c_name,
            element_type=c_type,
            is_abstract=cls.get("is_abstract", False),
        )
        db.add(class_elem)
        await db.flush()

        class_id_map[cls["id"]] = class_elem.id
        class_id_map[c_name] = class_elem.id

        for idx, attr in enumerate(cls.get("attributes", [])):
            vis_str = attr.get("visibility", "public").lower()
            vis = VisibilityEnum.public
            if vis_str in ["private", "-"]:
                vis = VisibilityEnum.private
            elif vis_str in ["protected", "#"]:
                vis = VisibilityEnum.protected
            elif vis_str in ["package", "~"]:
                vis = VisibilityEnum.package

            attr_elem = Attribute(
                class_id=class_elem.id,
                name=attr.get("name", "attr"),
                data_type=attr.get("data_type", "VARCHAR"),
                visibility=vis,
                is_pkey=attr.get("is_pkey", False),
                order_index=idx,
            )
            db.add(attr_elem)

        pos = cls.get("position", {"x": 100.0, "y": 100.0})
        be = BoardElement(
            board_id=board_id,
            class_id=class_elem.id,
            x=pos.get("x", 100.0),
            y=pos.get("y", 100.0),
            width=pos.get("w", 220.0),
            height=pos.get("h", 160.0),
        )
        db.add(be)

        imported_classes.append(c_name)

    imported_associations = 0
    for assoc in parsed.get("associations", []):
        src_raw = assoc.get("sourceId")
        tgt_raw = assoc.get("targetId")
        src_id = class_id_map.get(src_raw)
        tgt_id = class_id_map.get(tgt_raw)

        if not src_id or not tgt_id:
            continue

        rel_type_str = assoc.get("type", "association").lower()
        assoc_type = AssociationType.association
        if "generalization" in rel_type_str:
            assoc_type = AssociationType.generalization
        elif "realization" in rel_type_str:
            assoc_type = AssociationType.realization
        elif "aggregation" in rel_type_str:
            assoc_type = AssociationType.aggregation
        elif "composition" in rel_type_str:
            assoc_type = AssociationType.composition

        assoc_elem = Association(
            source_class_id=src_id,
            target_class_id=tgt_id,
            type=assoc_type,
            name=assoc.get("name"),
        )
        db.add(assoc_elem)
        imported_associations += 1

    await db.commit()

    return {
        "status": "success",
        "message": f"Se importaron {len(imported_classes)} clases y {imported_associations} relaciones.",
        "classes": imported_classes,
        "associations_count": imported_associations,
    }
