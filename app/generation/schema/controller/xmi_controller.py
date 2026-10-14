"""
xmi_controller.py — Endpoints de Importación y Exportación XMI 2.1 (Enterprise Architect).
Controlador delgado (Thin Controller) que delega la orquestación a XmiApplicationService
y la persistencia a XmiRepository, eliminando consultas N+1 y acoplamiento ORM.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.websocket.manager import manager
from app.workspace.projects.entity.project_entity import ProjectRole
from app.core.dependencies import require_board_access, BoardAuthContext
from app.generation.schema.repository.xmi_repository import XmiRepository
from app.generation.schema.service.xmi_application_service import XmiApplicationService
from app.generation.schema.dto.xmi_dto import XmiPreviewResponseDTO, XmiImportResponse
from app.generation.schema.exception.schema_exceptions import (
    BoardNotFoundException, XmiParsingError
)

router = APIRouter()


def _get_xmi_service(db: AsyncSession) -> XmiApplicationService:
    repo = XmiRepository(db)
    return XmiApplicationService(repo)


@router.get("/boards/{board_id}/export/xmi")
async def export_board_xmi(
    board_id: str,
    selected_class_ids: Optional[str] = Query(
        None,
        alias="class_ids",
        description="IDs de clases separados por coma para exportar por selección",
    ),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """Exporta el diagrama y modelo del tablero a formato XMI 2.1 compatible con Enterprise Architect."""
    service = _get_xmi_service(db)
    try:
        xml_content, filename = await service.export_board_xmi(
            board_id=board_id,
            selected_class_ids=selected_class_ids,
        )
    except BoardNotFoundException:
        raise HTTPException(status_code=404, detail="Board not found")

    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/boards/{board_id}/import/xmi/preview", response_model=XmiPreviewResponseDTO)
async def preview_board_xmi(
    board_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    """
    Inspección previa sin mutación: parsea el XMI y compara contra el estado actual
    para informar qué clases se crearán, cuáles se actualizarán y posibles advertencias.
    """
    try:
        content_bytes = await file.read()
        xml_str = content_bytes.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo XML: {str(e)}")

    service = _get_xmi_service(db)
    try:
        return await service.preview_board_xmi(board_id=board_id, xml_str=xml_str)
    except BoardNotFoundException:
        raise HTTPException(status_code=404, detail="Board not found")
    except XmiParsingError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/boards/{board_id}/import/xmi", response_model=XmiImportResponse)
async def import_board_xmi(
    board_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    """
    Importa un archivo XMI/XML de Enterprise Architect al tablero con deduplicación activa,
    soporte de roles/multiplicidades, registro en board_history y difusión WebSocket.
    """
    try:
        content_bytes = await file.read()
        xml_str = content_bytes.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo XML: {str(e)}")

    service = _get_xmi_service(db)
    filename = getattr(file, "filename", "imported.xmi") or "imported.xmi"
    try:
        response_dto, normalized_state = await service.import_board_xmi(
            board_id=board_id,
            xml_str=xml_str,
            filename=filename,
        )
    except BoardNotFoundException:
        raise HTTPException(status_code=404, detail="Board not found")
    except XmiParsingError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Difusión en tiempo real por WebSocket a todos los peers conectados
    if normalized_state:
        try:
            await manager.broadcast(
                board_id,
                {
                    "type": "state:sync",
                    "data": normalized_state,
                },
            )
        except Exception:
            pass

    return response_dto
