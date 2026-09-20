"""
guide_controller.py — Router API para el Agente de Guía Espacial y Onboarding.
Separado del router de chat: no devuelve comandos para el canvas,
sino orientación conceptual, explicaciones contextuales y avance del tour.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_board_access, BoardAuthContext
from app.workspace.projects.entity.project_entity import ProjectRole
from app.modeling.ai.dto.ai_dto import ExplainInput, AskInput, StepInput
from app.modeling.ai.service.guide_service import (
    explain_target,
    ask_guide,
    record_completed_step,
    get_or_create_guide_session,
)

router = APIRouter()


@router.post("/boards/{board_id}/explain")
async def explain_target_endpoint(
    board_id: str,
    data: ExplainInput,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    """
    Explica el elemento sobre el que se soltó la burbuja guía.
    Combina catálogo estático con razonamiento de Vertex AI cuando es dinámico.
    """
    caller_user_id = str(auth.user.id)
    result = await explain_target(
        db,
        board_id=board_id,
        target_type=data.target_type,
        target_meta=data.target_meta,
        session_token=data.session_token,
        user_id=caller_user_id,
    )
    return result


@router.post("/boards/{board_id}/ask")
async def ask_guide_endpoint(
    board_id: str,
    data: AskInput,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    """
    Responde a preguntas formuladas al agente de guía.
    """
    caller_user_id = str(auth.user.id)
    result = await ask_guide(
        db,
        board_id=board_id,
        question=data.question,
        target_context=data.target_context,
        session_token=data.session_token,
        user_id=caller_user_id,
    )
    return result


@router.post("/boards/{board_id}/step")
async def complete_step_endpoint(
    board_id: str,
    data: StepInput,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    """
    Registra el progreso del tour de onboarding guiado.
    """
    caller_user_id = str(auth.user.id)
    completed = await record_completed_step(
        db,
        board_id=board_id,
        session_token=data.session_token,
        step_id=data.step_id,
        user_id=caller_user_id,
    )
    return {"completed_steps": completed}


@router.get("/boards/{board_id}/session/{session_token}")
async def get_session_endpoint(
    board_id: str,
    session_token: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    """
    Obtiene el estado de la sesión de guía y pasos completados.
    """
    session = await get_or_create_guide_session(db, board_id, session_token)
    return {
        "board_id": session.board_id,
        "session_token": session.session_token,
        "completed_steps": session.completed_steps or [],
        "dismissed_at": str(session.dismissed_at) if session.dismissed_at else None,
    }

