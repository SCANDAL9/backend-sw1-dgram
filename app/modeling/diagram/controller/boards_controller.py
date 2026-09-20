from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import BoardSnapshot
from app.modeling.diagram.dto.board_dto import BoardCreate, BoardResponse, BoardUpdate
from app.modeling.diagram.service import board_service
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state

router = APIRouter()


import asyncio

import logging

logger = logging.getLogger(__name__)

async def _get_board_summary_info(db: AsyncSession, board_id: str) -> tuple[int, int, list[str]]:
    """Extrae el conteo de clases, relaciones y previsualización de nombres."""
    try:
        snap_stmt = (
            select(BoardSnapshot)
            .where(BoardSnapshot.board_id == board_id)
            .order_by(BoardSnapshot.version.desc())
            .limit(1)
        )
        res = await db.execute(snap_stmt)
        snap = None
        if hasattr(res, "scalar_one_or_none"):
            snap_val = res.scalar_one_or_none()
            if not asyncio.iscoroutine(snap_val):
                snap = snap_val
        if snap and isinstance(getattr(snap, "snapshot", None), dict):
            ents = snap.snapshot.get("entities") or snap.snapshot.get("classes") or []
            rels = snap.snapshot.get("relations") or snap.snapshot.get("associations") or []
            names = [e.get("name") for e in ents if e.get("name")][:3]
            return len(ents), len(rels), names

        state = await get_normalized_board_state(db, board_id)
        if state and isinstance(state, dict):
            ents = state.get("entities") or []
            rels = state.get("relations") or []
            names = [e.get("name") for e in ents if e.get("name")][:3]
            return len(ents), len(rels), names
    except Exception as exc:
        logger.warning(
            "No se pudo extraer resumen para board %s: %s",
            board_id,
            exc,
        )

    return 0, 0, []



from app.core.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_board_access,
    BoardAuthContext,
)
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import ProjectRole


@router.post("", response_model=BoardResponse)
async def create_board(
    data: BoardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.project_id:
        from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole
        project = await db.get(Project, data.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
        if project.owner_id != current_user.id:
            stmt = select(ProjectMember).where(
                ProjectMember.project_id == data.project_id,
                ProjectMember.user_id == current_user.id,
            )
            res = await db.execute(stmt)
            pm = res.scalar_one_or_none()
            if not pm or ROLE_LEVELS[pm.role] < ROLE_LEVELS[ProjectRole.editor]:
                raise HTTPException(status_code=403, detail="Permisos insuficientes para crear tableros en este proyecto")

    board = await board_service.create_board(
        db,
        name=data.name,
        owner_id=current_user.id,
        description=data.description,
        project_id=data.project_id,
    )
    return BoardResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        owner_id=board.owner_id,
        project_id=board.project_id,
        diagram_version=board.diagram_version or 0,
        entities_count=0,
        relations_count=0,
        preview_entities=[],
        created_at=str(board.created_at),
    )


@router.get("", response_model=list[BoardResponse])
async def list_boards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    boards = await board_service.list_boards_for_user(db, current_user.id)
    responses = []
    for b in boards:
        e_cnt, r_cnt, names = await _get_board_summary_info(db, b.id)
        responses.append(
            BoardResponse(
                id=b.id,
                name=b.name,
                description=b.description,
                owner_id=b.owner_id,
                project_id=b.project_id,
                diagram_version=b.diagram_version or 0,
                entities_count=e_cnt,
                relations_count=r_cnt,
                preview_entities=names,
                created_at=str(b.created_at),
            )
        )
    return responses


@router.get("/{board_id}", response_model=BoardResponse)
async def get_board(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    board = auth.board
    e_cnt, r_cnt, names = await _get_board_summary_info(db, board.id)
    return BoardResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        owner_id=board.owner_id,
        project_id=board.project_id,
        diagram_version=board.diagram_version or 0,
        entities_count=e_cnt,
        relations_count=r_cnt,
        preview_entities=names,
        created_at=str(board.created_at),
    )


@router.get("/{board_id}/state")
async def get_board_state(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    state = await get_normalized_board_state(db, board_id)
    if state:
        return state

    board = auth.board
    return {"entities": [], "relations": [], "classes": [], "associations": [], "version": board.diagram_version or 0}


@router.put("/{board_id}/snapshot")
async def save_snapshot(
    board_id: str,
    snapshot: dict,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
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
    board = await board_service.update_board(db, board_id, name=data.name, description=data.description)
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    e_cnt, r_cnt, names = await _get_board_summary_info(db, board.id)
    return BoardResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        owner_id=board.owner_id,
        project_id=board.project_id,
        diagram_version=board.diagram_version or 0,
        entities_count=e_cnt,
        relations_count=r_cnt,
        preview_entities=names,
        created_at=str(board.created_at),
    )

