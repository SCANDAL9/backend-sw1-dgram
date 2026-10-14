"""
boards_controller.py — Endpoints para gestión de tableros de diagramado UML (CU3).
Controlador delgado (Thin Controller) que delega la lógica de negocio y persistencia a board_service.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modeling.diagram.dto.board_dto import BoardCreate, BoardResponse, BoardUpdate
from app.modeling.diagram.mapper.board_mapper import board_to_response_dto
from app.modeling.diagram.service import board_service
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.core.dependencies import (
    get_current_user,
    require_board_access,
    BoardAuthContext,
)
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import ProjectRole

router = APIRouter()


@router.post("", response_model=BoardResponse)
async def create_board(
    data: BoardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crea un nuevo tablero asociado opcionalmente a un proyecto existente."""
    if data.project_id:
        await board_service.validate_project_board_creation(
            db=db,
            project_id=data.project_id,
            user_id=current_user.id,
        )

    board = await board_service.create_board(
        db,
        name=data.name,
        owner_id=current_user.id,
        description=data.description,
        project_id=data.project_id,
    )
    return board_to_response_dto(board)


@router.get("", response_model=list[BoardResponse])
async def list_boards(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista todos los tableros accesibles por el usuario con estadísticas resumidas en batch y paginación."""
    boards = await board_service.list_boards_for_user(db, current_user.id, limit=limit, offset=offset)
    if not boards:
        return []
    board_ids = [b.id for b in boards]
    summary_map = await board_service.get_boards_summary_batch(db, board_ids)
    responses = []
    for b in boards:
        e_cnt, r_cnt, names = summary_map.get(b.id, (0, 0, []))
        responses.append(board_to_response_dto(b, e_cnt, r_cnt, names))
    return responses


@router.get("/{board_id}", response_model=BoardResponse)
async def get_board(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """Obtiene los metadatos y resumen de un tablero específico."""
    board = auth.board
    e_cnt, r_cnt, names = await board_service.get_board_summary_info(db, board.id)
    return board_to_response_dto(board, e_cnt, r_cnt, names)


@router.get("/{board_id}/state")
async def get_board_state(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """Obtiene el estado completo reconstruido (entidades y relaciones) del tablero."""
    state = await get_normalized_board_state(db, board_id)
    if state:
        return state

    board = auth.board
    return {
        "entities": [],
        "relations": [],
        "classes": [],
        "associations": [],
        "version": board.diagram_version or 0,
    }


@router.put("/{board_id}/snapshot")
async def save_snapshot(
    board_id: str,
    snapshot: dict,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    """Persiste un snapshot JSON estructurado para el tablero."""
    saved = await board_service.save_snapshot(db, board_id, snapshot)
    if not saved:
        raise HTTPException(status_code=404, detail="Board not found")
    return {"status": "saved"}


@router.delete("/{board_id}")
async def delete_board(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.owner)),
):
    """Elimina permanentemente un tablero."""
    ok = await board_service.delete_board(db, board_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Board not found")
    return {"status": "deleted"}


@router.patch("/{board_id}", response_model=BoardResponse)
async def update_board(
    board_id: str,
    data: BoardUpdate,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    """Actualiza metadatos del tablero (nombre, descripción)."""
    board = await board_service.update_board(
        db, board_id, name=data.name, description=data.description
    )
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    e_cnt, r_cnt, names = await board_service.get_board_summary_info(db, board.id)
    return board_to_response_dto(board, e_cnt, r_cnt, names)


# Backward compatibility alias
_get_board_summary_info = board_service.get_board_summary_info

