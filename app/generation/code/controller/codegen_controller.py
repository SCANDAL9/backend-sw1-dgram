"""
codegen_controller.py — Router API para generación de proyectos Spring Boot Java 21.
Controlador delgado (Thin Controller) que delega la persistencia a CodegenRepository
y la generación a CodegenService, eliminando el acoplamiento directo con SQLAlchemy.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    BoardAuthContext,
    get_current_user,
    require_board_access,
)
from app.generation.code.mapper.codegen_mapper import CodegenMapper
from app.generation.code.service.codegen_service import CodegenService
from app.generation.code.repository.codegen_repository import CodegenRepository
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import ProjectRole

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
    repo = CodegenRepository(db)
    try:
        state = await repo.get_board_state(board_id)

        service = CodegenService(base_package=base_package)
        files = service.generate_files(state)

        # Registro de trazabilidad y auditoría mediante CodegenRepository
        actor_id = (
            auth_ctx.user.id
            if auth_ctx.user and auth_ctx.user.id and not str(auth_ctx.user.id).startswith("guest")
            else None
        )
        await repo.record_codegen_history(
            board_id=board_id,
            actor_id=actor_id,
            model_version=board.diagram_version,
            command_id=f"cmd-codegen-{uuid.uuid4()}",
            payload={"base_package": base_package, "files_count": len(files)},
        )

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
    repo = CodegenRepository(db)
    board = await repo.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    await repo.verify_board_access_for_user(board, current_user)

    state = await repo.get_board_state(board_id)
    service = CodegenService(base_package=base_package)
    zip_bytes = service.generate_zip(state)

    # Registro de auditoría de descarga mediante CodegenRepository
    actor_id = (
        current_user.id
        if current_user and current_user.id and not str(current_user.id).startswith("guest")
        else None
    )
    await repo.record_codegen_history(
        board_id=board_id,
        actor_id=actor_id,
        model_version=board.diagram_version,
        command_id=f"cmd-download-{uuid.uuid4()}",
        payload={"action": "download_zip", "base_package": base_package},
    )

    filename = f"{board.name.lower().replace(' ', '_')}_spring_boot.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
