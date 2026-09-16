"""
backfill_boards.py — Backfill offline idempotente de boards hacia el esquema normalizado (Fase 3).

Ejecución:
    python -m scripts.backfill_boards

Acciones:
  1. Verifica el usuario sistema fijo (00000000-0000-0000-0000-000000000001).
  2. Itera sobre boards con diagram_snapshot o sin project_id.
  3. Crea Project y Package ('default') para cada board.
  4. Parsea entities/classes, attributes/columns, relations/associations.
  5. Inserta class_element, board_element, attribute, association, board_snapshots.
  6. Es completamente idempotente (ON CONFLICT DO NOTHING / verificación de existencia).
"""
import asyncio
import json
import logging
import uuid
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session_factory
from app.modeling.diagram.entity.board_entity import Board
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import Project
from app.modeling.diagram.entity.uml_entity import (
    Package,
    ClassElement,
    Attribute,
    Association,
    ClassSource,
    VisibilityEnum,
    AssociationType,
)
from app.modeling.diagram.entity.board_normalized_entity import BoardElement, BoardSnapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


def coerce_uuid(val: str | None) -> str:
    if not val:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(val))
    except ValueError:
        # Genera UUID determinista basado en namespace para que sea idempotente
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"dgram.entity.{val}"))


def parse_assoc_type(raw_type: str | None) -> AssociationType:
    if not raw_type:
        return AssociationType.association
    val = raw_type.lower()
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


async def backfill_single_board(session: AsyncSession, board: Board) -> dict:
    stats = {"classes": 0, "attributes": 0, "associations": 0}

    # 1. Asegurar project_id
    project_id = board.project_id
    if not project_id:
        owner_id = board.owner_id
        owner_exists = (await session.get(User, owner_id)) is not None if owner_id else False
        valid_owner = owner_id if owner_exists else SYSTEM_USER_ID

        # Buscar proyecto existente con el nombre del board
        proj_res = await session.execute(
            select(Project).where(Project.owner_id == valid_owner, Project.name == board.name)
        )
        project = proj_res.scalar_one_or_none()
        if not project:
            project = Project(
                id=str(uuid.uuid4()),
                name=board.name or "Untitled Project",
                description=board.description,
                owner_id=valid_owner,
            )
            session.add(project)
            await session.flush()
        project_id = project.id
        board.project_id = project_id

    # 2. Asegurar package default
    pkg_res = await session.execute(
        select(Package).where(Package.project_id == project_id, Package.name == "default")
    )
    package = pkg_res.scalar_one_or_none()
    if not package:
        package = Package(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name="default",
        )
        session.add(package)
        await session.flush()
    package_id = package.id

    # 3. Parsear snapshot
    if not board.diagram_snapshot:
        return stats

    try:
        state = json.loads(board.diagram_snapshot)
    except Exception as e:
        logger.warning(f"Board {board.id} has invalid JSON in diagram_snapshot: {e}")
        return stats

    raw_entities = state.get("entities") or state.get("classes") or []
    raw_relations = state.get("relations") or state.get("associations") or []
    version = int(state.get("version", 0))
    board.diagram_version = version

    # 4. Procesar entidades / clases
    id_map: dict[str, str] = {}  # raw_id -> class_uuid

    for idx, e in enumerate(raw_entities):
        raw_id = str(e.get("id") or f"entity-{idx + 1}")
        class_uuid = coerce_uuid(raw_id)
        id_map[raw_id] = class_uuid
        name = (e.get("name") or f"Class_{idx + 1}").strip()
        is_abstract = bool(e.get("is_abstract", False))

        # Upsert class_element
        ce = await session.get(ClassElement, class_uuid)
        if not ce:
            ce = ClassElement(
                id=class_uuid,
                package_id=package_id,
                name=name,
                is_abstract=is_abstract,
                source=ClassSource.manual,
            )
            session.add(ce)
            stats["classes"] += 1

        # Upsert board_element (posición)
        be_res = await session.execute(
            select(BoardElement).where(
                BoardElement.board_id == board.id,
                BoardElement.class_id == class_uuid,
            )
        )
        be = be_res.scalar_one_or_none()
        pos = e.get("position", {}) or {}
        pos_x = float(pos.get("x", 100))
        pos_y = float(pos.get("y", 100))
        pos_w = float(pos.get("width")) if pos.get("width") else None
        pos_h = float(pos.get("height")) if pos.get("height") else None

        if not be:
            be = BoardElement(
                id=str(uuid.uuid4()),
                board_id=board.id,
                class_id=class_uuid,
                x=pos_x,
                y=pos_y,
                width=pos_w,
                height=pos_h,
            )
            session.add(be)

        # Atributos / Columnas
        cols = e.get("attributes") or e.get("columns") or []
        seen_names: set[str] = set()

        for c_idx, col in enumerate(cols):
            raw_col_name = str(col.get("name") or f"attr_{c_idx + 1}").strip()
            # Dedup de nombres de atributos como en DiagramService
            col_name = raw_col_name
            dup_counter = 2
            while col_name in seen_names:
                col_name = f"{raw_col_name}_{dup_counter}"
                dup_counter += 1
            seen_names.add(col_name)

            data_type = str(col.get("type") or "VARCHAR")
            pk = bool(col.get("pk", False))
            fk = bool(col.get("fk", False))

            attr_id = str(uuid.uuid5(uuid.UUID(class_uuid), f"attr.{col_name}"))
            existing_attr = await session.get(Attribute, attr_id)
            if not existing_attr:
                attr = Attribute(
                    id=attr_id,
                    class_id=class_uuid,
                    name=col_name,
                    data_type=data_type,
                    visibility=VisibilityEnum.public,
                    is_primary_key=pk,
                    is_foreign_key=fk,
                    order_index=c_idx,
                )
                session.add(attr)
                stats["attributes"] += 1

    await session.flush()

    # 5. Procesar relaciones / asociaciones
    for r_idx, r in enumerate(raw_relations):
        raw_src = str(r.get("sourceId") or r.get("sourceClassId") or r.get("source_id") or "")
        raw_tgt = str(r.get("targetId") or r.get("targetClassId") or r.get("target_id") or "")

        src_uuid = id_map.get(raw_src, coerce_uuid(raw_src) if raw_src else None)
        tgt_uuid = id_map.get(raw_tgt, coerce_uuid(raw_tgt) if raw_tgt else None)

        if not src_uuid or not tgt_uuid:
            continue

        # Verificar que existan ambas clases
        src_ce = await session.get(ClassElement, src_uuid)
        tgt_ce = await session.get(ClassElement, tgt_uuid)
        if not src_ce or not tgt_ce:
            continue

        raw_rel_id = str(r.get("id") or f"rel-{r_idx + 1}")
        assoc_uuid = coerce_uuid(f"{board.id}:{raw_rel_id}")
        existing_assoc = await session.get(Association, assoc_uuid)
        if not existing_assoc:
            assoc = Association(
                id=assoc_uuid,
                source_class_id=src_uuid,
                target_class_id=tgt_uuid,
                type=parse_assoc_type(r.get("type")),
                name=r.get("name"),
                source_role=r.get("sourceRole"),
                target_role=r.get("targetRole"),
                source_multiplicity=r.get("sourceMultiplicity"),
                target_multiplicity=r.get("targetMultiplicity"),
            )
            session.add(assoc)
            stats["associations"] += 1

    # 6. Snapshot de caché
    snap_res = await session.execute(
        select(BoardSnapshot).where(
            BoardSnapshot.board_id == board.id,
            BoardSnapshot.version == version,
        )
    )
    if not snap_res.scalar_one_or_none():
        snapshot_entry = BoardSnapshot(
            id=str(uuid.uuid4()),
            board_id=board.id,
            version=version,
            snapshot=state,
            created_by=SYSTEM_USER_ID,
        )
        session.add(snapshot_entry)

    return stats


async def run_backfill() -> None:
    logger.info("Iniciando backfill de boards hacia el esquema normalizado...")
    async with async_session_factory() as session:
        # 1. Asegurar usuario sistema
        sys_user = await session.get(User, SYSTEM_USER_ID)
        if not sys_user:
            sys_user = User(
                id=SYSTEM_USER_ID,
                full_name="Sistema dgram",
                email="system@dgram.internal",
            )
            session.add(sys_user)
            await session.commit()
            logger.info("Usuario sistema creado.")

        # 2. Cargar todos los boards
        boards_res = await session.execute(select(Board))
        boards = boards_res.scalars().all()
        logger.info(f"Se encontraron {len(boards)} boards en la base de datos.")

        total_stats = {"classes": 0, "attributes": 0, "associations": 0, "boards": len(boards)}

        for board in boards:
            stats = await backfill_single_board(session, board)
            total_stats["classes"] += stats["classes"]
            total_stats["attributes"] += stats["attributes"]
            total_stats["associations"] += stats["associations"]

        await session.commit()
        logger.info(f"Backfill completado exitosamente:")
        logger.info(f" - Boards procesados: {total_stats['boards']}")
        logger.info(f" - Clases creadas: {total_stats['classes']}")
        logger.info(f" - Atributos creados: {total_stats['attributes']}")
        logger.info(f" - Asociaciones creadas: {total_stats['associations']}")


if __name__ == "__main__":
    asyncio.run(run_backfill())
