"""
history_restore_service.py — Motor de restauración de versiones del diagrama.
Permite revertir el diagrama a un snapshot o versión previa de forma segura (append-only),
incrementando diagram_version, guardando la auditoría en board_history y
sincronizando a los colaboradores activos vía WebSocket.
"""
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from fastapi import HTTPException

from app.core.database import async_session_factory
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import (
    BoardElement, BoardSnapshot, BoardHistory, ActorTypeEnum
)
from app.modeling.diagram.entity.uml_entity import (
    ClassElement, Attribute, Association, ClassifierType, VisibilityEnum, AssociationType
)
from app.modeling.diagram.service.relational_mutator_service import (
    ensure_project_and_package, parse_classifier_type
)
from app.workspace.history.service.state_reconstructor_service import (
    coerce_uuid, parse_assoc_type
)

logger = logging.getLogger(__name__)


async def _execute_restore_on_session(
    session: AsyncSession,
    board_id: str,
    target_version: int,
    actor_id: str | None = None,
) -> tuple[dict, int]:
    board = await session.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")

    # 1. Localizar el snapshot correspondiente o más cercano
    snap_stmt = select(BoardSnapshot).where(
        BoardSnapshot.board_id == board_id,
        BoardSnapshot.version == target_version,
    )
    snap_res = await session.execute(snap_stmt)
    snapshot_entry = snap_res.scalar_one_or_none()

    if not snapshot_entry:
        # Fallback: buscar el snapshot más cercano disponible
        fallback_stmt = (
            select(BoardSnapshot)
            .where(BoardSnapshot.board_id == board_id)
            .order_by(func.abs(BoardSnapshot.version - target_version))
            .limit(1)
        )
        fallback_res = await session.execute(fallback_stmt)
        snapshot_entry = fallback_res.scalar_one_or_none()

    if not snapshot_entry:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontraron snapshots para restaurar el tablero '{board_id}'",
        )

    raw_snapshot = snapshot_entry.snapshot or {}
    entities = raw_snapshot.get("entities") or raw_snapshot.get("classes") or []
    relations = raw_snapshot.get("relations") or raw_snapshot.get("associations") or []
    packages = raw_snapshot.get("packages") or []

    current_version = board.diagram_version or 0
    new_version = current_version + 1

    # Actualizar versión de diagrama (OCC)
    board.diagram_version = new_version
    session.add(board)

    # Asegurar project y default package
    project_id, default_pkg_id = await ensure_project_and_package(session, board)

    # 2. Reemplazar elementos visuales en board_element
    await session.execute(
        delete(BoardElement).where(BoardElement.board_id == board_id)
    )

    # Insertar o actualizar clases y atributos desde el snapshot
    for ent in entities:
        ent_id = coerce_uuid(ent.get("id") or ent.get("class_id") or str(uuid.uuid4()))
        name = ent.get("name") or ent.get("class_name") or "Entity"
        elem_type_raw = ent.get("stereotype") or ent.get("elementType") or ent.get("element_type")
        classifier_type = parse_classifier_type(elem_type_raw)
        is_abs = bool(ent.get("is_abstract") or classifier_type == ClassifierType.abstract_class)
        pkg_id = ent.get("package_id") or default_pkg_id

        # Buscar o crear ClassElement
        cls = await session.get(ClassElement, ent_id)
        if not cls:
            cls = ClassElement(
                id=ent_id,
                package_id=pkg_id,
                name=name,
                element_type=classifier_type,
                is_abstract=is_abs,
            )
            session.add(cls)
            await session.flush()
        else:
            cls.name = name
            cls.element_type = classifier_type
            cls.is_abstract = is_abs


        # Crear BoardElement con posición
        pos = ent.get("position") or {}
        be = BoardElement(
            board_id=board_id,
            class_id=ent_id,
            x=float(pos.get("x", 100)),
            y=float(pos.get("y", 100)),
            width=float(ent.get("width", 220)),
            height=float(ent.get("height", 140)),
        )
        session.add(be)


        # Reemplazar atributos si se proporcionan
        columns = ent.get("columns") or ent.get("attributes") or []
        if columns:
            await session.execute(
                delete(Attribute).where(Attribute.class_id == ent_id)
            )
            for idx, col in enumerate(columns):
                attr = Attribute(
                    id=coerce_uuid(col.get("id") or str(uuid.uuid4())),
                    class_id=ent_id,
                    name=col.get("name", f"attr_{idx}"),
                    data_type=col.get("type", "String"),
                    is_pkey=bool(col.get("pk", False)),
                    visibility=VisibilityEnum.public,
                    order_index=idx,
                )
                session.add(attr)

    # 3. Registrar comando RESTORE_VERSION en board_history
    restore_cmd_id = f"cmd-restore-{uuid.uuid4()}"
    safe_actor_id = (
        actor_id
        if actor_id and actor_id != "guest" and not str(actor_id).startswith("guest")
        else None
    )
    history_entry = BoardHistory(
        id=str(uuid.uuid4()),
        board_id=board_id,
        command_id=restore_cmd_id,
        command_type="RESTORE_VERSION",
        payload={
            "restored_from_version": target_version,
            "previous_version": current_version,
            "entities_restored": len(entities),
            "relations_restored": len(relations),
        },
        actor_id=safe_actor_id,
        actor_type=ActorTypeEnum.user,
        model_version=new_version,
    )
    session.add(history_entry)

    # 4. Guardar nuevo checkpoint en board_snapshots
    new_snap = BoardSnapshot(
        id=str(uuid.uuid4()),
        board_id=board_id,
        version=new_version,
        snapshot=raw_snapshot,
        created_by=actor_id or board.owner_id,
    )
    session.add(new_snap)
    await session.commit()

    return raw_snapshot, new_version


async def restore_board_version(
    board_id: str,
    target_version: int,
    actor_id: str | None = None,
    db: AsyncSession | None = None,
) -> dict:
    """
    Restaura el estado del diagrama al snapshot correspondiente a target_version.
    Aplica una estrategia de reversión limpia hacia adelante:
      1. Recupera el snapshot histórico.
      2. Muta las tablas relacionales y eleva diagram_version a version_actual + 1.
      3. Registra el evento RESTORE_VERSION en board_history.
      4. Guarda nuevo checkpoint en board_snapshots.
      5. Actualiza memoria CommandHandler y emite broadcast state:sync vía WebSocket.
    """
    if db is not None:
        raw_snapshot, new_version = await _execute_restore_on_session(
            db, board_id, target_version, actor_id
        )
    else:
        async with async_session_factory() as session:
            raw_snapshot, new_version = await _execute_restore_on_session(
                session, board_id, target_version, actor_id
            )

    entities = raw_snapshot.get("entities") or raw_snapshot.get("classes") or []
    relations = raw_snapshot.get("relations") or raw_snapshot.get("associations") or []
    packages = raw_snapshot.get("packages") or []

    # 5. Sincronizar memoria CommandHandler en tiempo de ejecución
    try:
        from app.core.websocket.handlers import _handlers
        if board_id in _handlers:
            handler = _handlers[board_id]
            handler.version = new_version
            handler.entities = {e.get("id"): e for e in entities if e.get("id")}
            handler.relations = {r.get("id"): r for r in relations if r.get("id")}
            handler.packages = {p.get("id"): p for p in packages if p.get("id")}
    except Exception as exc:
        logger.warning("No se pudo actualizar _handlers en memoria para board %s: %s", board_id, exc)

    # 6. Notificar a los colaboradores en la sala vía WebSocket
    try:
        from app.core.websocket.handlers import manager
        sync_payload = {
            "version": new_version,
            "entities": entities,
            "relations": relations,
            "packages": packages,
        }
        await manager.broadcast(
            board_id,
            {
                "type": "state:sync",
                "data": sync_payload,
            },
        )
    except Exception as exc:
        logger.warning("No se pudo emitir broadcast state:sync tras restauración en board %s: %s", board_id, exc)

    return {
        "success": True,
        "restored_version": target_version,
        "new_diagram_version": new_version,
        "message": f"Diagrama restaurado con éxito a la versión {target_version} (nueva versión: v{new_version})",
    }
