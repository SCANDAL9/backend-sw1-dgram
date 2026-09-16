"""
project_memory_service.py — Servicio de Persistent Memory Bank para decisiones arquitectónicas.
Permite almacenar, consultar y eliminar directivas de diseño, convenciones y restricciones
vinculadas a proyectos de dgram.
"""
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.workspace.projects.entity.project_entity import ProjectMemory, Project
from app.modeling.diagram.entity.board_entity import Board

logger = logging.getLogger(__name__)


async def get_memories_for_project(
    db: AsyncSession,
    project_id: str,
) -> list[ProjectMemory]:
    """Retorna todas las directivas de arquitectura guardadas para un proyecto."""
    try:
        stmt = (
            select(ProjectMemory)
            .where(ProjectMemory.project_id == project_id)
            .order_by(ProjectMemory.created_at.asc())
        )
        result = await db.execute(stmt)
        scalars = result.scalars()
        if hasattr(scalars, "all"):
            res = scalars.all()
            if hasattr(res, "__await__"):
                res = await res
            return list(res)
        return []
    except Exception as exc:
        logger.warning("Error consultando directivas para project %s: %s", project_id, exc)
        return []


async def get_memories_for_board(
    db: AsyncSession,
    board_id: str,
) -> list[ProjectMemory]:
    """Retorna las directivas arquitectónicas del proyecto al que pertenece el tablero."""
    try:
        board = await db.get(Board, board_id)
        if not board or not getattr(board, "project_id", None):
            return []
        return await get_memories_for_project(db, str(board.project_id))
    except Exception as exc:
        logger.warning("No se pudieron cargar memorias del proyecto para board %s: %s", board_id, exc)
        return []



async def add_memory(
    db: AsyncSession,
    project_id: str,
    directive: str,
    category: str = "convention",
    user_id: str | None = None,
) -> ProjectMemory:
    """Registra una nueva directiva o convención en el Memory Bank."""
    memory = ProjectMemory(
        id=str(uuid.uuid4()),
        project_id=project_id,
        category=category,
        directive=directive.strip(),
        created_by=user_id,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def delete_memory(
    db: AsyncSession,
    memory_id: str,
) -> bool:
    """Elimina una directiva del Memory Bank."""
    memory = await db.get(ProjectMemory, memory_id)
    if not memory:
        return False
    await db.delete(memory)
    await db.commit()
    return True
