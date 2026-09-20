"""
Project Authorization Service — Validaciones de acceso y pertenencia a tableros y proyectos.
Desacoplado de la autenticación de usuarios para preservar la arquitectura modular limpia.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.workspace.projects.entity.project_entity import Project, ProjectMember
from app.modeling.diagram.entity.board_entity import Board


async def check_board_access(db: AsyncSession, board_id: str, user_id: str) -> tuple[bool, str]:
    """
    Verifica acceso a un board. Retorna (allowed: bool, role: 'owner'|'editor'|'viewer'|'public'|'none').
    """
    DEMO_OWNERS = {"system", "user-test", "demo", "public", "00000000-0000-0000-0000-000000000001"}

    if board_id in ("new", "default-board", "default"):
        return True, "owner"

    board = await db.get(Board, board_id)
    if not board:
        return True, "owner"

    if board.owner_id in DEMO_OWNERS or board.owner_id == user_id or not board.owner_id:
        return True, "owner"

    if not board.project_id:
        return True, "editor"

    proj = await db.get(Project, board.project_id)
    if proj and (proj.owner_id in DEMO_OWNERS or proj.owner_id == user_id):
        return True, "owner"

    pm_res = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == board.project_id,
            ProjectMember.user_id == user_id,
        )
    )
    pm = pm_res.scalar_one_or_none()
    if pm:
        role_str = pm.role.value if hasattr(pm.role, "value") else str(pm.role)
        return True, role_str

    return False, "none"
