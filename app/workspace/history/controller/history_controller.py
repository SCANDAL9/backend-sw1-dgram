"""
Controller / Router para consulta de historial, timeline, diffs y snapshots (CU7).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.workspace.history.service.command_history_service import CommandHistory
from app.workspace.history.service.history_restore_service import restore_board_version
from app.workspace.history.dto.history_dto import (
    HistoryItemDTO, HistoryDetailDTO, RestoreVersionResponseDTO
)
from app.modeling.diagram.entity.board_normalized_entity import BoardSnapshot
from app.core.dependencies import require_board_access, BoardAuthContext
from app.workspace.projects.entity.project_entity import ProjectRole

router = APIRouter()


@router.get("/boards/{board_id}/history", response_model=list[HistoryItemDTO])
async def get_board_history(
    board_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor_type: str | None = Query(None, description="user, ai o null"),
    command_type: str | None = Query(None, description="Filtro por tipo de comando"),
    from_version: int | None = Query(None, ge=0),
    to_version: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """Obtiene la línea temporal de cambios del tablero con soporte de filtrado."""
    history = CommandHistory(board_id, db=db)
    entries = await history.get_history_entries(
        limit=limit,
        offset=offset,
        actor_type=actor_type,
        command_type=command_type,
        from_version=from_version,
        to_version=to_version,
    )
    return [HistoryItemDTO(**e) for e in entries]


@router.get("/boards/{board_id}/history/{history_id}", response_model=HistoryDetailDTO)
async def get_history_entry_detail(
    board_id: str,
    history_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """Obtiene el detalle y diff de un cambio individual en el historial."""
    history = CommandHistory(board_id, db=db)
    detail = await history.get_entry_detail(history_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Entrada de historial no encontrada")
    return HistoryDetailDTO(**detail)


@router.get("/boards/{board_id}/snapshots")
async def get_board_snapshots(
    board_id: str,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """Lista los checkpoints de snapshots persistidos para el tablero."""
    stmt = (
        select(BoardSnapshot)
        .where(BoardSnapshot.board_id == board_id)
        .order_by(BoardSnapshot.version.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    snapshots = res.scalars().all()
    return [
        {
            "id": s.id,
            "version": s.version,
            "created_by": s.created_by,
        }
        for s in snapshots
    ]


@router.post("/boards/{board_id}/restore/{version}", response_model=RestoreVersionResponseDTO)
async def restore_version(
    board_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    """
    Restaura el diagrama al estado correspondiente a una versión anterior.
    Requiere permisos de editor o propietario. Aplica la reversión hacia adelante (OCC)
    y sincroniza en tiempo real vía WebSocket.
    """
    result = await restore_board_version(
        board_id=board_id,
        target_version=version,
        actor_id=auth.user.id,
        db=db,
    )
    return RestoreVersionResponseDTO(**result)

