"""
codegen_controller.py — Router API para generación de proyectos Spring Boot Java 21.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modeling.diagram.entity.board_entity import Board
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.generation.code.service.codegen_service import CodegenService
from app.generation.code.mapper.codegen_mapper import CodegenMapper

router = APIRouter()


@router.post("/boards/{board_id}")
async def generate_code_for_board(
    board_id: str,
    base_package: str = Query("com.dgram.generated", description="Paquete base para Java"),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera el proyecto de código Spring Boot en memoria para el board y lo devuelve en JSON.
    """
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    try:
        state = await get_normalized_board_state(db, board_id)
        if not state:
            state = {"entities": [], "relations": []}

        service = CodegenService(base_package=base_package)
        files = service.generate_files(state)

        return CodegenMapper.to_response(base_package, files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando código: {str(e)}")


@router.get("/boards/{board_id}/download")
async def download_code_zip(
    board_id: str,
    base_package: str = Query("com.dgram.generated"),
    db: AsyncSession = Depends(get_db),
):
    """
    Descarga el proyecto generado directamente como un archivo .zip
    """
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    state = await get_normalized_board_state(db, board_id)
    if not state:
        state = {"entities": [], "relations": []}

    service = CodegenService(base_package=base_package)
    zip_bytes = service.generate_zip(state)

    filename = f"{board.name.lower().replace(' ', '_')}_spring_boot.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
