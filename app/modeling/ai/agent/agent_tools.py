"""
agent_tools.py — Catálogo de Tools fuertemente tipadas para Google ADK y el subsistema de agentes.
Todas las herramientas reciben y retornan modelos Pydantic estructurados (cero prosa/texto libre).

Categorías:
1. Herramientas de Observación (Lectura directa de PostgreSQL normalizado)
2. Herramientas de Interacción con la UI (Client Actions via WebSocket)
3. Herramientas de Mutación (Command Protocol con CommandHandler)
"""
from typing import Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.modeling.diagram.entity.uml_entity import ClassElement, Attribute, Association
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.dto.command_dto import Command
from app.modeling.diagram.dto.command_dto import CommandType
from app.modeling.diagram.dto.command_dto import CommandPayload
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state


# ─────────────────────────────────────────────────────────────────────────────
# 1. ESQUEMAS DE OBSERVACIÓN
# ─────────────────────────────────────────────────────────────────────────────

class AttributeDetail(BaseModel):
    name: str
    type: str
    pk: bool = False
    fk: bool = False
    nullable: bool = False
    order_index: int = 0


class AssociationDetail(BaseModel):
    id: str
    target_class_name: str
    type: str
    source_multiplicity: str | None = None
    target_multiplicity: str | None = None
    name: str | None = None


class ClassDetail(BaseModel):
    id: str
    name: str
    element_type: str = "class"
    stereotype: str | None = None
    is_abstract: bool = False
    attributes: list[AttributeDetail] = Field(default_factory=list)
    associations: list[AssociationDetail] = Field(default_factory=list)


class DiagramSummary(BaseModel):
    board_id: str
    total_classes: int
    total_attributes: int
    total_associations: int
    class_names: list[str]


class ProjectMemoryItem(BaseModel):
    category: str
    directive: str



# ─────────────────────────────────────────────────────────────────────────────
# 2. ESQUEMAS DE CLIENT TOOLS (UI ACTIONS)
# ─────────────────────────────────────────────────────────────────────────────

class ClientUIAction(BaseModel):
    action_type: str = Field(..., description="Tipo de acción UI: highlight, focus, pan, open_panel")
    target_id: str | None = None
    pulse_color: str = "indigo"
    tab: str | None = None
    message: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 3. ESQUEMAS DE MUTACIÓN (COMMAND PROTOCOL)
# ─────────────────────────────────────────────────────────────────────────────

class CommandExecutionResult(BaseModel):
    status: str
    command_id: str
    command_type: str
    applied_to_board: str
    detail: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# IMPLEMENTACIÓN DE TOOLS
# ─────────────────────────────────────────────────────────────────────────────

async def tool_get_class_details(
    db: AsyncSession,
    board_id: str,
    class_name: str,
) -> ClassDetail | None:
    """
    Tool de observación: Consulta los detalles reales de una clase (atributos y relaciones)
    directamente desde el modelo normalizado de PostgreSQL.
    """
    board = await db.get(Board, board_id)
    if not board:
        return None

    # Buscar clase por nombre insensible a mayúsculas vinculada al proyecto mediante Package
    from app.modeling.diagram.entity.uml_entity import Package
    stmt = (
        select(ClassElement)
        .join(Package, ClassElement.package_id == Package.id)
        .where(
            Package.project_id == board.project_id,
            ClassElement.name.ilike(class_name.strip()),
        )
        .limit(1)
    )
    res = await db.execute(stmt)
    class_elem = res.scalar_one_or_none()
    if not class_elem:
        return None

    # Atributos reales
    attr_stmt = (
        select(Attribute)
        .where(Attribute.class_id == class_elem.id)
        .order_by(Attribute.order_index.asc())
    )
    attr_res = await db.execute(attr_stmt)
    attrs = [
        AttributeDetail(
            name=a.name,
            type=a.data_type,
            pk=bool(a.is_pkey),
            fk=bool(a.is_fkey),
            nullable=True,
            order_index=a.order_index,
        )
        for a in attr_res.scalars().all()
    ]

    # Asociaciones donde esta clase sea origen o destino
    assoc_stmt = (
        select(Association)
        .where(
            (Association.source_class_id == class_elem.id) |
            (Association.target_class_id == class_elem.id)
        )
    )
    assoc_res = await db.execute(assoc_stmt)
    assocs_list: list[AssociationDetail] = []
    for a in assoc_res.scalars().all():
        is_source = (a.source_class_id == class_elem.id)
        other_class_id = a.target_class_id if is_source else a.source_class_id
        other_class = await db.get(ClassElement, other_class_id)
        other_name = other_class.name if other_class else "Unknown"

        assocs_list.append(
            AssociationDetail(
                id=a.id,
                target_class_name=other_name,
                type=a.type.value if hasattr(a.type, "value") else str(a.type),
                source_multiplicity=a.source_multiplicity,
                target_multiplicity=a.target_multiplicity,
                name=a.name,
            )
        )

    return ClassDetail(
        id=class_elem.id,
        name=class_elem.name,
        element_type=class_elem.element_type.value if hasattr(class_elem.element_type, "value") else str(class_elem.element_type),
        stereotype=getattr(class_elem, "stereotype", None),
        is_abstract=bool(class_elem.is_abstract),
        attributes=attrs,
        associations=assocs_list,
    )


async def tool_get_diagram_summary(
    db: AsyncSession,
    board_id: str,
) -> DiagramSummary:
    """
    Tool de observación: Obtiene resumen y métricas de todas las clases y relaciones en el tablero.
    """
    state = await get_normalized_board_state(db, board_id) or {}
    entities = state.get("entities", [])
    relations = state.get("relations", [])

    class_names = [e.get("name", "") for e in entities if e.get("name")]
    total_attrs = sum(len(e.get("attributes", [])) for e in entities)

    return DiagramSummary(
        board_id=board_id,
        total_classes=len(entities),
        total_attributes=total_attrs,
        total_associations=len(relations),
        class_names=class_names,
    )


async def tool_execute_diagram_command(
    db: AsyncSession,
    board_id: str,
    command_type: str,
    payload_dict: dict[str, Any],
    actor: str = "ai:adk-agent",
) -> CommandExecutionResult:
    """
    Tool de mutación: Pasa rigurosamente por el Command Protocol y CommandHandler.
    Valida en memoria con CommandHandler, persiste en PostgreSQL (tablas normalizadas + board_history)
    y asegura idempotencia y versionado del modelo.
    """
    from app.modeling.diagram.service.command_handler_service import CommandHandler
    from app.workspace.history.service.command_history_service import CommandHistory
    from app.modeling.diagram.service.relational_mutator_service import apply_command_to_relational_db
    from app.modeling.diagram.service import board_service

    cmd_type_enum = CommandType(command_type)
    cmd_payload = CommandPayload(**payload_dict)

    cmd = Command(
        command_type=cmd_type_enum,
        payload=cmd_payload,
        actor=actor,
    )

    history = CommandHistory(board_id)
    handler = CommandHandler(board_id, history)

    # 1. Cargar snapshot actual si existe
    state = await get_normalized_board_state(db, board_id)
    if state:
        handler.load_snapshot(state)

    # 2. Ejecutar validación y mutación en CommandHandler
    res = await handler.execute(cmd)
    if not res.success:
        return CommandExecutionResult(
            status="failed",
            command_id=cmd.command_id,
            command_type=cmd_type_enum.value,
            applied_to_board=board_id,
            detail=res.error,
        )

    # 3. Persistir en base de datos relacional de forma atómica
    try:
        await apply_command_to_relational_db(
            db,
            board_id=board_id,
            command=cmd,
            actor_id=actor,
        )

        payload_dict_clean = (
            cmd.payload.model_dump()
            if hasattr(cmd.payload, "model_dump")
            else dict(cmd.payload)
        )

        await board_service.save_snapshot_normalized(
            db,
            board_id=board_id,
            state=handler.get_state(),
            command_id=cmd.command_id,
            command_type=cmd_type_enum.value,
            payload=payload_dict_clean,
            actor_id=actor,
            model_version=handler.version,
            expected_version=handler.version - 1,
            actor=actor,
        )
    except Exception as e:
        return CommandExecutionResult(
            status="failed",
            command_id=cmd.command_id,
            command_type=cmd_type_enum.value,
            applied_to_board=board_id,
            detail=f"Database persistence error: {str(e)}",
        )

    return CommandExecutionResult(
        status="success",
        command_id=cmd.command_id,
        command_type=cmd_type_enum.value,
        applied_to_board=board_id,
        detail=f"Version: {handler.version}",
    )


async def tool_emit_ui_action(
    board_id: str,
    action_type: str,
    target_id: str | None = None,
    pulse_color: str = "indigo",
    tab: str | None = None,
    message: str | None = None,
) -> ClientUIAction:
    """
    Tool de interacción UI: Envía un evento reactivo WebSocket a los clientes conectados
    al tablero para resaltar elementos, enfocar el viewport o mostrar pistas visuales.
    """
    action = ClientUIAction(
        action_type=action_type,
        target_id=target_id,
        pulse_color=pulse_color,
        tab=tab,
        message=message,
    )
    try:
        from app.core.websocket.manager import manager
        await manager.broadcast(
            board_id=board_id,
            message={
                "type": "agent:ui_action",
                "data": action.model_dump(),
            },
        )
    except Exception as e:
        logger.warning("No se pudo emitir agent:ui_action por WebSocket: %s", e)

    return action


async def tool_get_project_memory(
    db: AsyncSession,
    board_id: str,
) -> list[ProjectMemoryItem]:
    """
    Tool de observación del Memory Bank: Consulta las directivas de arquitectura,
    convenciones de diseño y reglas de negocio persistentes guardadas para el proyecto.
    """
    from app.modeling.ai.service.project_memory_service import get_memories_for_board
    memories = await get_memories_for_board(db, board_id)
    return [
        ProjectMemoryItem(category=m.category, directive=m.directive)
        for m in memories
    ]


