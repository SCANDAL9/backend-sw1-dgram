"""
relational_mutator.py — Sincronizador atómico de comandos a tablas relacionales normalizadas.
Muta directamente: class_element, attribute, association, board_element, package, project.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, update, select
from app.modeling.diagram.entity.board_entity import Board
from app.workspace.projects.entity.project_entity import Project
from app.modeling.diagram.entity.uml_entity import (
    Package, ClassElement, Attribute, Association, AssociationType, VisibilityEnum, ClassifierType,
    AssociationClassLink, ClassSource
)
from app.modeling.diagram.entity.board_normalized_entity import BoardElement
from app.modeling.diagram.dto.command_dto import Command
from app.workspace.history.service.state_reconstructor_service import coerce_uuid, parse_assoc_type
from app.modeling.diagram.repository.element_repository import ElementRepository


def parse_visibility(raw_vis: str | None) -> VisibilityEnum:
    if not raw_vis:
        return VisibilityEnum.public
    val = str(raw_vis).lower().strip()
    mapping = {
        "public": VisibilityEnum.public,
        "private": VisibilityEnum.private,
        "protected": VisibilityEnum.protected,
        "package": VisibilityEnum.package,
    }
    return mapping.get(val, VisibilityEnum.public)


def parse_class_source(raw_src: str | None) -> ClassSource:
    if not raw_src:
        return ClassSource.manual
    val = str(raw_src).lower().strip()
    mapping = {
        "manual": ClassSource.manual,
        "archi_import": ClassSource.archi_import,
        "image_ocr": ClassSource.image_ocr,
        "ocr": ClassSource.image_ocr,
    }
    return mapping.get(val, ClassSource.manual)


def parse_classifier_type(raw_type: str | None) -> ClassifierType:
    if not raw_type:
        return ClassifierType.class_
    val = str(raw_type).lower().strip()
    mapping = {
        "class": ClassifierType.class_,
        "abstract_class": ClassifierType.abstract_class,
        "abstract": ClassifierType.abstract_class,
        "interface": ClassifierType.interface,
        "enumeration": ClassifierType.enumeration,
        "enum": ClassifierType.enumeration,
        "datatype": ClassifierType.datatype,
        "data_type": ClassifierType.datatype,
    }
    return mapping.get(val, ClassifierType.class_)


async def ensure_project_and_package(db: AsyncSession, board: Board) -> tuple[str, str]:
    """Garantiza que el board tenga project_id y un package default."""
    repo = ElementRepository(db)
    if not board.project_id:
        proj = await repo.get_project_by_owner(board.owner_id)
        if not proj:
            proj = Project(
                id=str(uuid.uuid4()),
                name=board.name or "Default Project",
                owner_id=board.owner_id if len(board.owner_id) == 36 else "00000000-0000-0000-0000-000000000001",
                description="Auto-created project for board",
            )
            db.add(proj)
            await db.flush()
        board.project_id = proj.id
        await db.flush()

    # Buscar o crear package default
    pkg = await repo.get_default_package_for_project(board.project_id)
    if not pkg:
        pkg = Package(
            id=str(uuid.uuid4()),
            project_id=board.project_id,
            name="default",
        )
        db.add(pkg)
        await db.flush()

    return board.project_id, pkg.id


async def apply_command_to_relational_db(
    db: AsyncSession,
    board_id: str,
    command: Command,
    actor_id: str | None = None,
) -> None:
    """Aplica la mutación relacional correspondiente a un comando sobre las 13 tablas."""
    board = await db.get(Board, board_id)
    if not board:
        return

    repo = ElementRepository(db)
    project_id, package_id = await ensure_project_and_package(db, board)
    cmd_type = command.command_type.value if hasattr(command.command_type, "value") else str(command.command_type)
    payload = command.payload.model_dump() if hasattr(command.payload, "model_dump") else dict(command.payload)

    # 1. Creación de Entidad/Clase
    if cmd_type in ("CREATE_ENTITY", "CREATE_CLASS"):
        raw_id = payload.get("entity_id") or payload.get("class_id") or str(uuid.uuid4())
        class_id = coerce_uuid(raw_id)
        class_name = payload.get("entity_name") or payload.get("class_name") or "Entity"
        elem_type_raw = payload.get("element_type") or payload.get("elementType") or payload.get("stereotype")
        classifier_type = parse_classifier_type(elem_type_raw)
        is_abs = bool(payload.get("is_abstract", False) or payload.get("isAbstract", False) or classifier_type == ClassifierType.abstract_class)
        raw_is_vis = payload.get("is_visible")
        if raw_is_vis is None:
            raw_is_vis = payload.get("isVisible")
        is_vis = True if raw_is_vis is None else bool(raw_is_vis)
        chosen_pkg_id = payload.get("package_id") or package_id

        pos = payload.get("position") or {"x": 100.0, "y": 100.0}
        w = payload.get("width")
        h = payload.get("height")

        # Verificar si ya existe ClassElement
        existing_class = await db.get(ClassElement, class_id)
        if not existing_class:
            # Validar unicidad en el paquete para evitar colisiones en codegen y modelo
            dup_stmt = select(ClassElement).where(
                ClassElement.package_id == chosen_pkg_id,
                ClassElement.name == class_name,
            )
            dup_res = await db.execute(dup_stmt)
            if dup_res.scalar_one_or_none():
                suffix = 2
                candidate = f"{class_name}_{suffix}"
                while True:
                    chk = await db.execute(
                        select(ClassElement).where(
                            ClassElement.package_id == chosen_pkg_id,
                            ClassElement.name == candidate,
                        )
                    )
                    if not chk.scalar_one_or_none():
                        class_name = candidate
                        break
                    suffix += 1
                    candidate = f"{class_name}_{suffix}"

            new_class = ClassElement(
                id=class_id,
                package_id=chosen_pkg_id,
                name=class_name,
                element_type=classifier_type,
                is_abstract=is_abs,
                is_visible=is_vis,
                source=parse_class_source(payload.get("source")),
                created_by=actor_id,
            )
            db.add(new_class)
            await db.flush()

            # Añadir atributos iniciales
            cols = payload.get("columns") or payload.get("attributes") or []
            for idx, col in enumerate(cols):
                attr = Attribute(
                    id=str(uuid.uuid4()),
                    class_id=class_id,
                    name=col.get("name", f"col_{idx}"),
                    data_type=col.get("type", "VARCHAR"),
                    visibility=parse_visibility(col.get("visibility")),
                    is_pkey=bool(col.get("pk", False)),
                    is_fkey=bool(col.get("fk", False)),
                    is_derived=bool(col.get("is_derived", False)),
                    default_value=col.get("default_value"),
                    order_index=idx,
                )
                db.add(attr)

        # Garantizar que el BoardElement exista y esté actualizado en este tablero
        existing_be = await repo.get_board_element(board_id, class_id)
        if not existing_be:
            board_elem = BoardElement(
                id=str(uuid.uuid4()),
                board_id=board_id,
                class_id=class_id,
                x=float(pos.get("x", 100.0)),
                y=float(pos.get("y", 100.0)),
                width=float(w) if w is not None else None,
                height=float(h) if h is not None else None,
            )
            db.add(board_elem)
        else:
            existing_be.x = float(pos.get("x", existing_be.x))
            existing_be.y = float(pos.get("y", existing_be.y))
            if w is not None:
                existing_be.width = float(w)
            if h is not None:
                existing_be.height = float(h)

    # 2. Desvinculación de Entidad/Clase del Tablero (DETACH no destructivo)
    elif cmd_type in ("DETACH_ENTITY", "DETACH_CLASS"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        if raw_id:
            class_id = coerce_uuid(raw_id)
            # Eliminar únicamente la vinculación visual con este tablero (BoardElement), preservando ClassElement en el catálogo
            await db.execute(delete(BoardElement).where(BoardElement.board_id == board_id, BoardElement.class_id == class_id))

    # 2.b Eliminación Definitiva de Entidad/Clase del Modelo
    elif cmd_type in ("DELETE_ENTITY", "DELETE_CLASS"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        if raw_id:
            class_id = coerce_uuid(raw_id)
            # Desvincular de association_class_link si actuaba como clase intermedia
            await db.execute(delete(AssociationClassLink).where(AssociationClassLink.class_id == class_id))
            # Eliminar board_element y class_element
            await db.execute(delete(BoardElement).where(BoardElement.board_id == board_id, BoardElement.class_id == class_id))
            await db.execute(delete(ClassElement).where(ClassElement.id == class_id))

    # 3. Actualización de Nombre / Abstract / Element Type de Entidad
    elif cmd_type in ("UPDATE_ENTITY", "UPDATE_CLASS"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        if raw_id:
            class_id = coerce_uuid(raw_id)
            cls_obj = await db.get(ClassElement, class_id)
            if cls_obj:
                old_name = cls_obj.name
                new_name = payload.get("entity_name") or payload.get("class_name") or payload.get("name")
                is_type = cls_obj.element_type in (ClassifierType.enumeration, ClassifierType.datatype)
                if new_name and new_name.strip() != old_name:
                    dup_stmt = select(ClassElement).where(
                        ClassElement.package_id == cls_obj.package_id,
                        ClassElement.name == new_name.strip(),
                        ClassElement.id != class_id,
                    )
                    dup_res = await db.execute(dup_stmt)
                    if dup_res.scalar_one_or_none():
                        raise ValueError(f"Ya existe otra clase con el nombre '{new_name}' en este paquete.")

                    cls_obj.name = new_name.strip()
                    if is_type and old_name and new_name.strip() != old_name:
                        await db.execute(
                            update(Attribute)
                            .where(Attribute.data_type == old_name)
                            .values(data_type=new_name.strip())
                        )
                elem_type_raw = payload.get("element_type") or payload.get("elementType") or payload.get("stereotype")
                if elem_type_raw is not None:
                    cls_obj.element_type = parse_classifier_type(elem_type_raw)
                if "is_abstract" in payload or "isAbstract" in payload:
                    cls_obj.is_abstract = bool(payload.get("is_abstract", False) or payload.get("isAbstract", False))
                raw_is_vis = payload.get("is_visible")
                if raw_is_vis is None:
                    raw_is_vis = payload.get("isVisible")
                if raw_is_vis is not None:
                    cls_obj.is_visible = bool(raw_is_vis)
                if "source" in payload and payload["source"]:
                    cls_obj.source = parse_class_source(payload["source"])
                if payload.get("package_id"):
                    cls_obj.package_id = payload["package_id"]

    # 4. Mover Entidad en Canvas
    elif cmd_type in ("MOVE_ENTITY", "MOVE_CLASS"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        pos = payload.get("position", {})
        if raw_id and pos:
            class_id = coerce_uuid(raw_id)
            be = await repo.get_board_element(board_id, class_id)
            if be:
                be.x = float(pos.get("x", be.x))
                be.y = float(pos.get("y", be.y))

    # 4.b Redimensionar Entidad en Canvas
    elif cmd_type in ("RESIZE_ENTITY", "RESIZE_CLASS"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        if raw_id:
            class_id = coerce_uuid(raw_id)
            be = await repo.get_board_element(board_id, class_id)
            if be:
                if payload.get("width") is not None:
                    be.width = float(payload["width"])
                if payload.get("height") is not None:
                    be.height = float(payload["height"])

    # 4.c Asignar Clase a Paquete
    elif cmd_type in ("ASSIGN_CLASS_PACKAGE",):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        target_pkg = payload.get("package_id")
        if raw_id and target_pkg:
            class_id = coerce_uuid(raw_id)
            cls_obj = await db.get(ClassElement, class_id)
            if cls_obj:
                cls_obj.package_id = target_pkg

    # 4.d Gestión de Paquetes UML
    elif cmd_type in ("CREATE_PACKAGE",):
        pkg_id = payload.get("package_id") or str(uuid.uuid4())
        pkg_name = payload.get("package_name") or payload.get("name") or "New Package"
        existing_pkg = await db.get(Package, pkg_id)
        if not existing_pkg:
            new_pkg = Package(id=pkg_id, project_id=project_id, name=pkg_name)
            db.add(new_pkg)

    elif cmd_type in ("UPDATE_PACKAGE",):
        pkg_id = payload.get("package_id")
        pkg_name = payload.get("package_name") or payload.get("name")
        if pkg_id and pkg_name:
            pkg_obj = await db.get(Package, pkg_id)
            if pkg_obj:
                pkg_obj.name = pkg_name

    elif cmd_type in ("DELETE_PACKAGE",):
        pkg_id = payload.get("package_id")
        if pkg_id and pkg_id != package_id:
            # Reasignar clases al paquete default antes de eliminar
            await db.execute(
                update(ClassElement).where(ClassElement.package_id == pkg_id).values(package_id=package_id)
            )
            await db.execute(delete(Package).where(Package.id == pkg_id))

    # 5. Añadir Columna / Atributo
    elif cmd_type in ("ADD_COLUMN", "ADD_ATTRIBUTE"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        col = payload.get("column") or payload.get("column_changes") or payload.get("attribute_changes") or payload
        if raw_id and col:
            class_id = coerce_uuid(raw_id)
            attr_name = col.get("name") or payload.get("column_name") or "new_col"
            attr = Attribute(
                id=str(uuid.uuid4()),
                class_id=class_id,
                name=attr_name,
                data_type=col.get("type", "VARCHAR"),
                visibility=parse_visibility(col.get("visibility")),
                is_pkey=bool(col.get("pk", False)),
                is_fkey=bool(col.get("fk", False)),
                is_derived=bool(col.get("is_derived") if "is_derived" in col else col.get("isDerived", False)),
                default_value=col.get("default_value") if "default_value" in col else col.get("defaultValue"),
                order_index=int(col.get("order_index", 0)),
            )
            db.add(attr)

    # 6. Actualizar Columna / Atributo
    elif cmd_type in ("UPDATE_COLUMN", "UPDATE_ATTRIBUTE"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        col_name = payload.get("column_name") or payload.get("attribute_name")
        changes = payload.get("column_changes") or payload.get("attribute_changes") or {}
        if raw_id and col_name:
            class_id = coerce_uuid(raw_id)
            attr = await repo.get_attribute_by_name(class_id, col_name)
            if attr:
                if "name" in changes:
                    attr.name = changes["name"]
                if "type" in changes:
                    attr.data_type = changes["type"]
                if "visibility" in changes:
                    attr.visibility = parse_visibility(changes["visibility"])
                if "pk" in changes:
                    attr.is_pkey = bool(changes["pk"])
                if "fk" in changes:
                    attr.is_fkey = bool(changes["fk"])
                if "is_derived" in changes or "isDerived" in changes:
                    attr.is_derived = bool(changes.get("is_derived") if "is_derived" in changes else changes.get("isDerived"))
                if "default_value" in changes or "defaultValue" in changes:
                    attr.default_value = changes.get("default_value") if "default_value" in changes else changes.get("defaultValue")

    # 7. Eliminar Columna / Atributo
    elif cmd_type in ("DELETE_COLUMN", "DELETE_ATTRIBUTE"):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        col_name = payload.get("column_name") or payload.get("attribute_name")
        if raw_id and col_name:
            class_id = coerce_uuid(raw_id)
            await db.execute(delete(Attribute).where(Attribute.class_id == class_id, Attribute.name == col_name))

    # 8. Crear Relación / Asociación
    elif cmd_type in ("CREATE_RELATION", "CREATE_ASSOCIATION"):
        raw_id = payload.get("relation_id") or payload.get("association_id") or str(uuid.uuid4())
        assoc_id = coerce_uuid(raw_id)
        src_id = coerce_uuid(payload.get("source_entity_id") or payload.get("source_id") or payload.get("source_class_id"))
        tgt_id = coerce_uuid(payload.get("target_entity_id") or payload.get("target_id") or payload.get("target_class_id"))
        rel_type_str = payload.get("relation_type") or payload.get("association_type") or payload.get("type") or "1:N"

        existing_assoc = await db.get(Association, assoc_id)
        if not existing_assoc:
            parsed_rel_type = parse_assoc_type(rel_type_str)

            # Validación semántica entre clasificadores
            if src_id == tgt_id and parsed_rel_type in (AssociationType.generalization, AssociationType.realization):
                raise ValueError("Un clasificador no puede tener relaciones de herencia o realización hacia sí mismo.")

            src_cls = await db.get(ClassElement, src_id)
            tgt_cls = await db.get(ClassElement, tgt_id)
            if src_cls and tgt_cls:
                src_t = (src_cls.element_type.value if hasattr(src_cls.element_type, "value") else str(src_cls.element_type)).lower()
                tgt_t = (tgt_cls.element_type.value if hasattr(tgt_cls.element_type, "value") else str(tgt_cls.element_type)).lower()

                if parsed_rel_type == AssociationType.generalization:
                    if "enum" in src_t or "enum" in tgt_t:
                        raise ValueError("Los clasificadores de tipo Enumeration no pueden participar en herencias.")
                    if "datatype" in src_t or "datatype" in tgt_t:
                        raise ValueError("Los clasificadores de tipo DataType no pueden participar en herencias.")
                    if src_t in ("class", "abstract_class") and tgt_t == "interface":
                        raise ValueError("Una clase no puede heredar de una interfaz; debe usar Realization.")
                    if src_t == "interface" and tgt_t in ("class", "abstract_class"):
                        raise ValueError("Una interfaz no puede heredar de una clase.")
                    if src_t in ("class", "abstract_class"):
                        if await repo.get_parent_generalization(src_id, AssociationType.generalization):
                            raise ValueError("Herencia múltiple entre clases no soportada por el modelo relacional ni Spring Boot.")
                elif parsed_rel_type == AssociationType.realization:
                    if tgt_t != "interface":
                        raise ValueError("La Realización solo puede tener como destino una Interfaz.")
                    if src_t == "interface":
                        raise ValueError("Una interfaz no realiza otra interfaz; debe heredar mediante Generalización.")
                    if "enum" in src_t or "datatype" in src_t:
                        raise ValueError("Los enums y datatypes no pueden realizar interfaces.")
                elif parsed_rel_type in (AssociationType.association, AssociationType.aggregation, AssociationType.composition):
                    if "enum" in src_t or "enum" in tgt_t:
                        raise ValueError("Los enums no pueden conectarse mediante asociaciones directas.")

            assoc = Association(
                id=assoc_id,
                source_class_id=src_id,
                target_class_id=tgt_id,
                type=parsed_rel_type,
                name=payload.get("name"),
                source_role=payload.get("source_role"),
                target_role=payload.get("target_role"),
                source_multiplicity=payload.get("source_multiplicity"),
                target_multiplicity=payload.get("target_multiplicity"),
            )
            db.add(assoc)

    # 8.b Actualizar Relación / Asociación
    elif cmd_type in ("UPDATE_RELATION", "UPDATE_ASSOCIATION"):
        raw_id = payload.get("relation_id") or payload.get("association_id")
        if raw_id:
            assoc_id = coerce_uuid(raw_id)
            assoc = await db.get(Association, assoc_id)
            if assoc:
                if payload.get("source_entity_id") or payload.get("source_id") or payload.get("source_class_id"):
                    assoc.source_class_id = coerce_uuid(payload.get("source_entity_id") or payload.get("source_id") or payload.get("source_class_id"))
                if payload.get("target_entity_id") or payload.get("target_id") or payload.get("target_class_id"):
                    assoc.target_class_id = coerce_uuid(payload.get("target_entity_id") or payload.get("target_id") or payload.get("target_class_id"))
                if payload.get("name") is not None:
                    assoc.name = payload["name"]
                if payload.get("relation_type") or payload.get("association_type") or payload.get("type"):
                    assoc.type = parse_assoc_type(payload.get("relation_type") or payload.get("association_type") or payload.get("type"))
                if "source_role" in payload:
                    assoc.source_role = payload["source_role"]
                if "target_role" in payload:
                    assoc.target_role = payload["target_role"]
                if "source_multiplicity" in payload:
                    assoc.source_multiplicity = payload["source_multiplicity"]
                if "target_multiplicity" in payload:
                    assoc.target_multiplicity = payload["target_multiplicity"]

    # 9. Eliminar Relación / Asociación
    elif cmd_type in ("DELETE_RELATION", "DELETE_ASSOCIATION"):
        raw_id = payload.get("relation_id") or payload.get("association_id")
        if raw_id:
            assoc_id = coerce_uuid(raw_id)
            await db.execute(delete(Association).where(Association.id == assoc_id))

    # 10. Vincular Clase de Asociación (UML Association Class)
    elif cmd_type in ("LINK_ASSOCIATION_CLASS",):
        assoc_raw = payload.get("relation_id") or payload.get("association_id")
        class_raw = payload.get("class_id") or payload.get("entity_id")
        if assoc_raw and class_raw:
            assoc_id = coerce_uuid(assoc_raw)
            class_id = coerce_uuid(class_raw)
            existing_link = await repo.get_association_class_link(assoc_id)
            if existing_link:
                existing_link.class_id = class_id
            else:
                db.add(AssociationClassLink(association_id=assoc_id, class_id=class_id))

    # 11. Desvincular Clase de Asociación
    elif cmd_type in ("UNLINK_ASSOCIATION_CLASS",):
        assoc_raw = payload.get("relation_id") or payload.get("association_id")
        if assoc_raw:
            assoc_id = coerce_uuid(assoc_raw)
            await db.execute(
                delete(AssociationClassLink).where(AssociationClassLink.association_id == assoc_id)
            )

    # 12. Creación Atómica de Clase de Asociación (Association Class)
    elif cmd_type in ("CREATE_ASSOCIATION_CLASS",):
        assoc_raw = payload.get("relation_id") or payload.get("association_id")
        raw_id = payload.get("entity_id") or payload.get("class_id") or str(uuid.uuid4())
        class_id = coerce_uuid(raw_id)
        class_name = payload.get("entity_name") or payload.get("class_name") or payload.get("name") or "AssociationClass"

        existing_class = await db.get(ClassElement, class_id)
        if not existing_class:
            new_class = ClassElement(
                id=class_id,
                package_id=package_id,
                name=class_name,
                element_type=ClassifierType.class_,
                is_abstract=False,
                is_visible=True,
                source=ClassSource.manual,
                created_by=actor_id,
            )
            db.add(new_class)
            await db.flush()

            cols = payload.get("columns") or payload.get("attributes") or []
            for idx, col in enumerate(cols):
                attr = Attribute(
                    id=str(uuid.uuid4()),
                    class_id=class_id,
                    name=col.get("name", f"col_{idx}"),
                    data_type=col.get("type", "VARCHAR"),
                    visibility=parse_visibility(col.get("visibility")),
                    is_pkey=bool(col.get("pk", False)),
                    is_fkey=bool(col.get("fk", False)),
                    is_derived=bool(col.get("is_derived", False)),
                    default_value=col.get("default_value"),
                    order_index=idx,
                )
                db.add(attr)

        existing_be = await repo.get_board_element(board_id, class_id)
        if not existing_be:
            pos = payload.get("position") or {"x": 250.0, "y": 250.0}
            board_elem = BoardElement(
                id=str(uuid.uuid4()),
                board_id=board_id,
                class_id=class_id,
                x=float(pos.get("x", 250.0)),
                y=float(pos.get("y", 250.0)),
            )
            db.add(board_elem)

        if assoc_raw:
            assoc_id = coerce_uuid(assoc_raw)
            existing_link = await repo.get_association_class_link(assoc_id)
            if existing_link:
                existing_link.class_id = class_id
            else:
                db.add(AssociationClassLink(association_id=assoc_id, class_id=class_id))

    # 13. Reordenamiento de Atributos
    elif cmd_type in ("REORDER_ATTRIBUTES",):
        raw_id = payload.get("entity_id") or payload.get("class_id")
        ordered_names = payload.get("ordered_attribute_names") or payload.get("ordered_names") or []
        if raw_id and ordered_names:
            class_id = coerce_uuid(raw_id)
            for idx, attr_name in enumerate(ordered_names):
                await db.execute(
                    update(Attribute)
                    .where(Attribute.class_id == class_id, Attribute.name == attr_name)
                    .values(order_index=idx)
                )
