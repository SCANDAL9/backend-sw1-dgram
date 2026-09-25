"""
codegen_controller.py — Router API para generación de proyectos Spring Boot Java 21.
Protegido con autenticación y control de acceso (RBAC) por tablero/proyecto.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    BoardAuthContext,
    ROLE_LEVELS,
    get_current_user,
    require_board_access,
)
from app.generation.code.mapper.codegen_mapper import CodegenMapper
from app.generation.code.service.codegen_service import CodegenService
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import (
    ActorTypeEnum,
    BoardHistory,
)
from app.workspace.authentication.entity.user_entity import User
from app.workspace.history.service.state_reconstructor_service import (
    get_normalized_board_state,
)
from app.workspace.projects.entity.project_entity import (
    Project,
    ProjectMember,
    ProjectRole,
)

router = APIRouter()


async def get_download_user(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Valida la identidad del usuario a través de Authorization Bearer o query param token."""
    auth_header = authorization
    if not auth_header and token:
        auth_header = f"Bearer {token}"
    if not auth_header:
        raise HTTPException(status_code=401, detail="Token de autorización requerido")
    return await get_current_user(authorization=auth_header, db=db)


async def verify_board_access_for_user(
    board: Board,
    user: User,
    db: AsyncSession,
    min_role: ProjectRole = ProjectRole.viewer,
) -> None:
    """Verifica que el usuario tenga privilegios para acceder al tablero o su proyecto."""
    if board.owner_id == user.id or board.owner_id == "system":
        return

    if board.project_id:
        project = await db.get(Project, board.project_id)
        if project:
            if project.owner_id == user.id:
                return
            stmt = select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
            res = await db.execute(stmt)
            pm = res.scalar_one_or_none()
            if pm and ROLE_LEVELS[pm.role] >= ROLE_LEVELS[min_role]:
                return

    raise HTTPException(status_code=403, detail="No tienes acceso a este tablero")


@router.post("/boards/{board_id}")
async def generate_code_for_board(
    board_id: str,
    base_package: str = Query("com.dgram.generated", description="Paquete base para Java"),
    auth_ctx: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera el proyecto de código Spring Boot en memoria para el board y lo devuelve en JSON.
    Requiere autenticación y membresía en el tablero o proyecto.
    """
    board = auth_ctx.board
    try:
        state = await get_normalized_board_state(db, board_id)
        if not state:
            state = {"entities": [], "relations": []}

        service = CodegenService(base_package=base_package)
        files = service.generate_files(state)

        # Registro de trazabilidad y auditoría en BoardHistory
        actor_id = (
            auth_ctx.user.id
            if auth_ctx.user and auth_ctx.user.id and not str(auth_ctx.user.id).startswith("guest")
            else None
        )
        history_entry = BoardHistory(
            id=str(uuid.uuid4()),
            board_id=board_id,
            command_id=f"cmd-codegen-{uuid.uuid4()}",
            actor_id=actor_id,
            command_type="GENERATE_CODE",
            payload={"base_package": base_package, "files_count": len(files)},
            actor_type=ActorTypeEnum.user,
            model_version=board.diagram_version,
        )
        db.add(history_entry)
        await db.commit()

        return CodegenMapper.to_response(base_package, files)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando código: {str(e)}")


@router.get("/boards/{board_id}/download")
async def download_code_zip(
    board_id: str,
    base_package: str = Query("com.dgram.generated"),
    current_user: User = Depends(get_download_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Descarga el proyecto generado directamente como un archivo .zip.
    Requiere autenticación mediante Header Authorization o query param token.
    """
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    await verify_board_access_for_user(board, current_user, db)

    state = await get_normalized_board_state(db, board_id)
    if not state:
        state = {"entities": [], "relations": []}

    service = CodegenService(base_package=base_package)
    zip_bytes = service.generate_zip(state)

    # Registro de auditoría de descarga
    actor_id = (
        current_user.id
        if current_user and current_user.id and not str(current_user.id).startswith("guest")
        else None
    )
    history_entry = BoardHistory(
        id=str(uuid.uuid4()),
        board_id=board_id,
        command_id=f"cmd-download-{uuid.uuid4()}",
        actor_id=actor_id,
        command_type="GENERATE_CODE",
        payload={"action": "download_zip", "base_package": base_package},
        actor_type=ActorTypeEnum.user,
        model_version=board.diagram_version,
    )
    db.add(history_entry)
    await db.commit()

    filename = f"{board.name.lower().replace(' ', '_')}_spring_boot.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
