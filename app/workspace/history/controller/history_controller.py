"""
Controller / Router para consulta de historial y snapshots (CU7).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.workspace.history.service.command_history_service import CommandHistory
from app.workspace.history.dto.history_dto import HistoryItemDTO
from app.core.dependencies import require_board_access, BoardAuthContext
from app.workspace.projects.entity.project_entity import ProjectRole

router = APIRouter()


@router.get("/boards/{board_id}/history", response_model=list[HistoryItemDTO])
async def get_board_history(
    board_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    history = CommandHistory(board_id)
    entries = await history.get_history_entries(limit=limit)
    return [HistoryItemDTO(**e) for e in entries]
