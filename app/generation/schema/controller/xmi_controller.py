"""
xmi_controller.py — Endpoints de Importación y Exportación XMI 2.1 (Enterprise Architect).
Soporta inspección previa (preview), deduplicación activa por external_ref y nombre,
extracción de roles y multiplicidades, consistencia con board_history y difusión WebSocket en tiempo real.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.core.database import get_db
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.uml_entity import (
    Package, ClassElement, Attribute, Association, AssociationClassLink,
    ClassifierType, VisibilityEnum, AssociationType, ClassSource
)
from app.modeling.diagram.entity.board_normalized_entity import BoardElement, BoardHistory, BoardSnapshot, ActorTypeEnum
from app.modeling.diagram.service.relational_mutator_service import ensure_project_and_package
from app.generation.schema.service.xmi_service import XmiExporter, XmiImporter
from app.generation.schema.mapper.schema_mapper import SchemaMapper
from app.generation.schema.dto.xmi_dto import (
    XmiPreviewResponseDTO, XmiPreviewClassDTO, XmiPreviewAssociationDTO, XmiImportResponse
)
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.core.websocket.manager import manager

from app.workspace.projects.entity.project_entity import ProjectRole
from app.core.dependencies import require_board_access, BoardAuthContext

router = APIRouter()


@router.get("/boards/{board_id}/export/xmi")
async def export_board_xmi(
    board_id: str,
    selected_class_ids: Optional[str] = Query(None, alias="class_ids", description="IDs de clases separados por coma para exportar por selección"),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
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
        classes_db = list(cls_all_res.scalars().all())
    else:
        cls_stmt = select(ClassElement).where(ClassElement.id.in_(class_ids))
        cls_res = await db.execute(cls_stmt)
        classes_db = list(cls_res.scalars().all())

    if selected_class_ids and isinstance(selected_class_ids, str):
        filter_set = {cid.strip() for cid in selected_class_ids.split(",") if cid.strip()}
        classes_db = [c for c in classes_db if c.id in filter_set]

    classes_payload = []
    for c in classes_db:
        attr_stmt = select(Attribute).where(Attribute.class_id == c.id).order_by(Attribute.order_index)
        attr_res = await db.execute(attr_stmt)
        attrs = attr_res.scalars().all()

        pos = dict(board_element_map.get(c.id, {"x": 100.0, "y": 100.0, "w": 200.0, "h": 70.0}))
        # Calcular altura ergonómica proporcional si height es nulo o el valor rígido por defecto (160.0)
        num_attrs = len(attrs)
        dynamic_h = max(56.0, 56.0 + (num_attrs * 18.0))
        if pos.get("h") in (None, 160.0):
            pos["h"] = dynamic_h
        board_element_map[c.id] = pos
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
        assoc_ids = [a.id for a in associations_db]

        assoc_class_map = {}
        if assoc_ids:
            acl_stmt = select(AssociationClassLink).where(AssociationClassLink.association_id.in_(assoc_ids))
            acl_res = await db.execute(acl_stmt)
            for acl in acl_res.scalars().all():
                assoc_class_map[acl.association_id] = acl.class_id

        assoc_payload = []
        for a in associations_db:
            ad = SchemaMapper.association_to_dict(a)
            if a.id in assoc_class_map:
                ad["association_class_id"] = assoc_class_map[a.id]
            # Normalizar multiplicidades si están en NULL en la base de datos
            if not ad.get("source_multiplicity") and not ad.get("target_multiplicity"):
                if ad.get("association_class_id"):
                    ad["source_multiplicity"] = "0..*"
                    ad["target_multiplicity"] = "0..*"
                else:
                    rel_t = str(ad.get("type", "")).lower()
                    if rel_t in ("association", "aggregation", "composition"):
                        ad["source_multiplicity"] = "1"
                        ad["target_multiplicity"] = "0..*"
            elif ad.get("association_class_id"):
                if not ad.get("source_multiplicity"):
                    ad["source_multiplicity"] = "0..*"
                if not ad.get("target_multiplicity"):
                    ad["target_multiplicity"] = "0..*"
            assoc_payload.append(ad)
    else:
        assoc_payload = []

    # Obtener paquetes del proyecto para conservar jerarquía en XMI (excluyendo el placeholder 'default' si es único)
    pkg_stmt = select(Package).where(Package.project_id == project_id)
    pkg_res = await db.execute(pkg_stmt)
    raw_pkgs = pkg_res.scalars().all()
    # Si solo existe el paquete técnico 'default', no lo enviamos como subpaquete para que las clases residan directamente en el paquete del Board
    if len(raw_pkgs) == 1 and raw_pkgs[0].name.lower() in ("default", "logical view"):
        packages_payload = []
    else:
        packages_payload = [{"id": p.id, "name": p.name} for p in raw_pkgs if p.name.lower() not in ("default", "logical view")]

    exporter = XmiExporter()
    xml_content = exporter.export_board(
        project_name=board.name,
        board_name=board.name,
        classes=classes_payload,
        associations=assoc_payload,
        board_elements=board_element_map,
        packages=packages_payload,
    )

    filename = f"{board.name.replace(' ', '_')}.xmi"
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/boards/{board_id}/import/xmi/preview", response_model=XmiPreviewResponseDTO)
async def preview_board_xmi(
    board_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """
    Inspección previa sin mutación: parsea el XMI y compara contra el estado actual
    para informar qué clases se crearán, cuáles se actualizarán y posibles advertencias.
    """
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    project_id, package_id = await ensure_project_and_package(db, board)
    await db.commit()

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

    # Obtener clases existentes en todo el proyecto
    existing_stmt = (
        select(ClassElement)
        .join(Package, ClassElement.package_id == Package.id)
        .where(Package.project_id == project_id)
    )
    existing_res = await db.execute(existing_stmt)
    existing_classes = existing_res.scalars().all()

    existing_by_ext_ref = {c.external_ref: c for c in existing_classes if c.external_ref}
    existing_by_name = {c.name.lower(): c for c in existing_classes}

    classes_to_create: list[XmiPreviewClassDTO] = []
    classes_to_update: list[XmiPreviewClassDTO] = []
    warnings: list[str] = []

    parsed_class_ids = set()

    for cls in parsed.get("classes", []):
        c_name = cls.get("name")
        if not c_name:
            warnings.append("Se detectó una clase sin nombre en el XMI; será ignorada.")
            continue

        c_id = cls.get("id")
        parsed_class_ids.add(c_id)
        parsed_class_ids.add(c_name)

        ext_ref = cls.get("external_ref")
        existing_match = None
        if ext_ref and ext_ref in existing_by_ext_ref:
            existing_match = existing_by_ext_ref[ext_ref]
        elif c_name.lower() in existing_by_name:
            existing_match = existing_by_name[c_name.lower()]

        attr_names = [a.get("name", "attr") for a in cls.get("attributes", [])]
        action = "update" if existing_match else "create"

        dto = XmiPreviewClassDTO(
            name=c_name,
            external_ref=ext_ref,
            element_type=cls.get("element_type", "class"),
            is_abstract=cls.get("is_abstract", False),
            attributes_count=len(attr_names),
            attributes=attr_names,
            action=action,
        )

        if action == "update":
            classes_to_update.append(dto)
        else:
            classes_to_create.append(dto)

    preview_assocs: list[XmiPreviewAssociationDTO] = []
    for assoc in parsed.get("associations", []):
        src_raw = assoc.get("sourceId")
        tgt_raw = assoc.get("targetId")

        if src_raw not in parsed_class_ids or tgt_raw not in parsed_class_ids:
            warnings.append(
                f"Relación '{assoc.get('name') or assoc.get('type')}' hace referencia a un clasificador no encontrado en el archivo."
            )
            continue

        preview_assocs.append(
            XmiPreviewAssociationDTO(
                type=assoc.get("type", "Association"),
                source_name=str(src_raw),
                target_name=str(tgt_raw),
                name=assoc.get("name"),
                source_role=assoc.get("source_role"),
                target_role=assoc.get("target_role"),
                source_multiplicity=assoc.get("source_multiplicity"),
                target_multiplicity=assoc.get("target_multiplicity"),
            )
        )

    return XmiPreviewResponseDTO(
        total_classes=len(classes_to_create) + len(classes_to_update),
        classes_to_create=classes_to_create,
        classes_to_update=classes_to_update,
        associations=preview_assocs,
        warnings=warnings,
    )


@router.post("/boards/{board_id}/import/xmi", response_model=XmiImportResponse)
async def import_board_xmi(
    board_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    """
    Importa un archivo XMI/XML de Enterprise Architect al tablero con deduplicación activa,
    soporte de roles/multiplicidades, registro en board_history y difusión WebSocket.
    """
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

    # Clases existentes en el proyecto para deduplicación
    existing_stmt = (
        select(ClassElement)
        .join(Package, ClassElement.package_id == Package.id)
        .where(Package.project_id == project_id)
    )
    existing_res = await db.execute(existing_stmt)
    existing_classes = existing_res.scalars().all()

    existing_by_ext_ref = {c.external_ref: c for c in existing_classes if c.external_ref}
    existing_by_name = {c.name.lower(): c for c in existing_classes}

    created_classes = []
    updated_classes = []
    class_id_map = {}

    # Paquetes del proyecto para asignación automática por jerarquía
    pkg_stmt = select(Package).where(Package.project_id == project_id)
    pkg_res = await db.execute(pkg_stmt)
    project_packages_by_name = {p.name.lower(): p for p in pkg_res.scalars().all()}

    for cls in parsed.get("classes", []):
        c_name = cls.get("name")
        if not c_name:
            continue

        ext_ref = cls.get("external_ref")
        c_type_str = cls.get("element_type", "class").lower()
        c_type = ClassifierType.interface if c_type_str == "interface" else ClassifierType.class_
        is_abs = cls.get("is_abstract", False)

        # Determinar si ya existe
        class_elem = None
        if ext_ref and ext_ref in existing_by_ext_ref:
            class_elem = existing_by_ext_ref[ext_ref]
        elif c_name.lower() in existing_by_name:
            class_elem = existing_by_name[c_name.lower()]

        if class_elem:
            # Actualización (Deduplicación activa)
            class_elem.name = c_name
            class_elem.element_type = c_type
            class_elem.is_abstract = is_abs
            if ext_ref and not class_elem.external_ref:
                class_elem.external_ref = ext_ref
            updated_classes.append(c_name)
        else:
            # Determinar paquete destino (conservando paquetes jerárquicos del XMI)
            target_pkg_id = package_id
            if cls.get("package_name"):
                p_name = cls.get("package_name")
                if p_name.lower() in project_packages_by_name:
                    target_pkg_id = project_packages_by_name[p_name.lower()].id
                else:
                    new_pkg = Package(project_id=project_id, name=p_name)
                    db.add(new_pkg)
                    await db.flush()
                    project_packages_by_name[p_name.lower()] = new_pkg
                    target_pkg_id = new_pkg.id

            # Creación
            class_elem = ClassElement(
                package_id=target_pkg_id,
                name=c_name,
                element_type=c_type,
                is_abstract=is_abs,
                external_ref=ext_ref,
                source=ClassSource.archi_import,
            )
            db.add(class_elem)
            await db.flush()
            created_classes.append(c_name)

        class_id_map[cls["id"]] = class_elem.id
        class_id_map[c_name] = class_elem.id

        # Atributos: fusionar/actualizar
        existing_attrs_stmt = select(Attribute).where(Attribute.class_id == class_elem.id)
        existing_attrs_res = await db.execute(existing_attrs_stmt)
        existing_attrs = {a.name.lower(): a for a in existing_attrs_res.scalars().all()}

        for idx, attr in enumerate(cls.get("attributes", [])):
            a_name = attr.get("name", "attr")
            vis_str = attr.get("visibility", "public").lower()
            vis = VisibilityEnum.public
            if vis_str in ["private", "-"]:
                vis = VisibilityEnum.private
            elif vis_str in ["protected", "#"]:
                vis = VisibilityEnum.protected
            elif vis_str in ["package", "~"]:
                vis = VisibilityEnum.package

            a_dtype = attr.get("data_type", "VARCHAR")
            a_pk = attr.get("is_pkey", False)

            if a_name.lower() in existing_attrs:
                existing_attr = existing_attrs[a_name.lower()]
                existing_attr.data_type = a_dtype
                existing_attr.visibility = vis
                existing_attr.is_pkey = a_pk
                existing_attr.order_index = idx
            else:
                new_attr = Attribute(
                    class_id=class_elem.id,
                    name=a_name,
                    data_type=a_dtype,
                    visibility=vis,
                    is_pkey=a_pk,
                    order_index=idx,
                )
                db.add(new_attr)

        # Geometría visual en BoardElement
        pos = cls.get("position", {"x": 100.0, "y": 100.0})
        be_stmt = select(BoardElement).where(
            BoardElement.board_id == board_id,
            BoardElement.class_id == class_elem.id
        )
        be_res = await db.execute(be_stmt)
        be = be_res.scalar_one_or_none()

        if be:
            be.x = pos.get("x", be.x)
            be.y = pos.get("y", be.y)
            be.width = pos.get("w", be.width or 220.0)
            be.height = pos.get("h", be.height or 160.0)
        else:
            be = BoardElement(
                board_id=board_id,
                class_id=class_elem.id,
                x=pos.get("x", 100.0),
                y=pos.get("y", 100.0),
                width=pos.get("w", 220.0),
                height=pos.get("h", 160.0),
            )
            db.add(be)

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

        # Deduplicar asociación existente entre las mismas dos clases
        existing_assoc_stmt = select(Association).where(
            Association.source_class_id == src_id,
            Association.target_class_id == tgt_id,
            Association.type == assoc_type,
        )
        existing_assoc_res = await db.execute(existing_assoc_stmt)
        assoc_elem = existing_assoc_res.scalar_one_or_none()

        if assoc_elem:
            assoc_elem.name = assoc.get("name") or assoc_elem.name
            assoc_elem.source_role = assoc.get("source_role") or assoc_elem.source_role
            assoc_elem.target_role = assoc.get("target_role") or assoc_elem.target_role
            assoc_elem.source_multiplicity = assoc.get("source_multiplicity") or assoc_elem.source_multiplicity
            assoc_elem.target_multiplicity = assoc.get("target_multiplicity") or assoc_elem.target_multiplicity
        else:
            assoc_elem = Association(
                source_class_id=src_id,
                target_class_id=tgt_id,
                type=assoc_type,
                name=assoc.get("name"),
                source_role=assoc.get("source_role"),
                target_role=assoc.get("target_role"),
                source_multiplicity=assoc.get("source_multiplicity"),
                target_multiplicity=assoc.get("target_multiplicity"),
            )
            db.add(assoc_elem)

        imported_associations += 1

    # Incrementar versión de tablero y registrar en board_history
    new_version = (board.diagram_version or 0) + 1
    board.diagram_version = new_version

    history_entry = BoardHistory(
        id=str(uuid.uuid4()),
        board_id=board_id,
        command_id=f"cmd-import-xmi-{uuid.uuid4()}",
        command_type="IMPORT_XMI",
        payload={
            "filename": getattr(file, "filename", "imported.xmi"),
            "created_count": len(created_classes),
            "updated_count": len(updated_classes),
            "associations_count": imported_associations,
        },
        actor_id=None,
        actor_type=ActorTypeEnum.user,
        model_version=new_version,
    )
    db.add(history_entry)

    await db.flush()

    # Guardar checkpoint de snapshot
    normalized_state = await get_normalized_board_state(db, board_id)
    if normalized_state:
        snap = BoardSnapshot(
            id=str(uuid.uuid4()),
            board_id=board_id,
            version=new_version,
            snapshot=normalized_state,
        )
        db.add(snap)

    await db.commit()

    # Difusión en tiempo real por WebSocket a todos los peers conectados
    if normalized_state:
        try:
            await manager.broadcast(
                board_id,
                {
                    "type": "state:sync",
                    "data": normalized_state,
                },
            )
        except Exception:
            pass

    return XmiImportResponse(
        status="success",
        message=f"Se procesaron {len(created_classes) + len(updated_classes)} clases ({len(created_classes)} creadas, {len(updated_classes)} actualizadas) y {imported_associations} relaciones.",
        classes=created_classes,
        updated_classes=updated_classes,
        associations_count=imported_associations,
    )
