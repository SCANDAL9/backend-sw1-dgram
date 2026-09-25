"""
guide_service.py — Servicio de coordinación para el Agente de Onboarding y Mentoría Contextual.
Mantiene las sesiones de guía, gestiona el avance de pasos y delega la generación de
explicaciones de arquitectura y modelado a Vertex AI / heurísticas de mentoría.
"""
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.ai.entity.guide_entity import GuideSession
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.modeling.ai.agent.vertex_client import vertex_ai_client


async def get_or_create_guide_session(
    db: AsyncSession,
    board_id: str,
    session_token: str,
    user_id: str | None = None,
) -> GuideSession:
    """Busca o crea una sesión persistente de guía y onboarding para este board."""
    clean_uid = (
        user_id
        if user_id
        and not str(user_id).startswith("guest")
        and not str(user_id).startswith("user-")
        and str(user_id) not in {"system", "demo", "public", "user-test"}
        else None
    )
    stmt = (
        select(GuideSession)
        .where(
            GuideSession.board_id == board_id,
            GuideSession.session_token == session_token,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        session = GuideSession(
            board_id=board_id,
            session_token=session_token,
            user_id=clean_uid,
            completed_steps=[],
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def record_completed_step(
    db: AsyncSession,
    board_id: str,
    session_token: str,
    step_id: str,
    user_id: str | None = None,
) -> list[str]:
    """Registra un paso completado en la sesión de onboarding."""
    session = await get_or_create_guide_session(db, board_id, session_token, user_id)
    steps = list(session.completed_steps or [])
    if step_id not in steps:
        steps.append(step_id)
        session.completed_steps = steps
        await db.commit()
        await db.refresh(session)
    return session.completed_steps


async def explain_target(
    db: AsyncSession,
    board_id: str,
    target_type: str,
    target_meta: dict[str, Any],
    session_token: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Genera la explicación para un elemento específico inspeccionado por la burbuja.
    """
    session = await get_or_create_guide_session(db, board_id, session_token, user_id)
    state = await get_normalized_board_state(db, board_id) or {}

    target_context = {
        "target_type": target_type,
        "target_meta": target_meta,
    }

    res = await vertex_ai_client.generate_guide_response(
        target_context=target_context,
        question=None,
        diagram_state=state,
    )
    res["session_token"] = session.session_token
    res["completed_steps"] = session.completed_steps
    return res


async def ask_guide(
    db: AsyncSession,
    board_id: str,
    question: str,
    target_context: dict[str, Any] | None,
    session_token: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Responde a una pregunta de seguimiento libre o predefinida formulada al agente de guía.
    """
    session = await get_or_create_guide_session(db, board_id, session_token, user_id)
    state = await get_normalized_board_state(db, board_id) or {}

    res = await vertex_ai_client.generate_guide_response(
        target_context=target_context or {"target_type": "general", "target_meta": {}},
        question=question,
        diagram_state=state,
    )
    res["session_token"] = session.session_token
    res["completed_steps"] = session.completed_steps
    return res
