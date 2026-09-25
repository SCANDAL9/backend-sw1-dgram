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

    board_owner_str = str(board.owner_id).strip() if board.owner_id else ""
    user_id_str = str(user_id).strip() if user_id else ""

    if (
        board_owner_str in DEMO_OWNERS
        or not board_owner_str
        or board_owner_str == user_id_str
    ):
        return True, "owner"

    if not board.project_id:
        return True, "editor"

    proj = await db.get(Project, board.project_id)
    if proj:
        proj_owner_str = str(proj.owner_id).strip() if proj.owner_id else ""
        if proj_owner_str in DEMO_OWNERS or proj_owner_str == user_id_str:
            return True, "owner"

    pm_res = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == board.project_id,
            ProjectMember.user_id == user_id_str,
        )
    )
    pm = pm_res.scalar_one_or_none()
    if pm:
        role_str = pm.role.value if hasattr(pm.role, "value") else str(pm.role)
        return True, role_str

    return False, "none"
