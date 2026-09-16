"""
dependencies.py — Dependencias centralizadas de autenticación y autorización RBAC para FastAPI.
"""
from dataclasses import dataclass
from typing import Callable
from fastapi import Depends, HTTPException, Header, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole
from app.modeling.diagram.entity.board_entity import Board
from app.workspace.authentication.service import auth_service


ROLE_LEVELS: dict[ProjectRole, int] = {
    ProjectRole.viewer: 10,
    ProjectRole.editor: 20,
    ProjectRole.owner: 30,
}


@dataclass
class ProjectAuthContext:
    user: User
    project: Project
    role: ProjectRole


@dataclass
class BoardAuthContext:
    user: User
    board: Board
    project: Project | None
    role: ProjectRole


async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extrae y valida el JWT del header Authorization: Bearer <token>."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token de autorización requerido")
    token = authorization.split(" ")[1]
    payload = auth_service.decode_jwt_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


async def get_current_user_optional(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Extrae el usuario si se suministra un token válido; de lo contrario retorna None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    payload = auth_service.decode_jwt_token(token)
    if not payload or "sub" not in payload:
        return None
    return await db.get(User, payload["sub"])


def require_project_role(min_role: ProjectRole = ProjectRole.viewer) -> Callable:
    """Fábrica de dependencias para validar acceso y rol en un proyecto."""
    async def _dependency(
        project_id: str = Path(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> ProjectAuthContext:
        project = await db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")

        # 1. El dueño administrativo tiene rol de owner completo
        if project.owner_id == current_user.id:
            user_role = ProjectRole.owner
        else:
            # 2. Consultar membresía en project_member
            stmt = select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == current_user.id,
            )
            res = await db.execute(stmt)
            pm = res.scalar_one_or_none()
            if not pm:
                raise HTTPException(status_code=403, detail="No perteneces a este proyecto")
            user_role = pm.role

        # 3. Comprobar jerarquía de roles
        if ROLE_LEVELS[user_role] < ROLE_LEVELS[min_role]:
            raise HTTPException(
                status_code=403,
                detail=f"Permisos insuficientes. Se requiere rol '{min_role.value}'",
            )

        return ProjectAuthContext(user=current_user, project=project, role=user_role)

    return _dependency


def require_board_access(min_role: ProjectRole = ProjectRole.viewer) -> Callable:
    """Fábrica de dependencias para validar acceso y rol en un tablero o su proyecto asociado."""
    async def _dependency(
        board_id: str = Path(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> BoardAuthContext:
        board = await db.get(Board, board_id)
        if not board:
            raise HTTPException(status_code=404, detail="Board not found")

        project = None
        user_role = None

        if board.owner_id == current_user.id or board.owner_id == "system":
            user_role = ProjectRole.owner

        if board.project_id:
            project = await db.get(Project, board.project_id)
            if project:
                if project.owner_id == current_user.id:
                    user_role = ProjectRole.owner
                else:
                    stmt = select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == current_user.id,
                    )
                    res = await db.execute(stmt)
                    pm = res.scalar_one_or_none()
                    if pm:
                        # Si ya tenía owner por board.owner_id prevalece el más alto
                        if not user_role or ROLE_LEVELS[pm.role] > ROLE_LEVELS[user_role]:
                            user_role = pm.role

        if not user_role:
            raise HTTPException(status_code=403, detail="No tienes acceso a este tablero")

        if ROLE_LEVELS[user_role] < ROLE_LEVELS[min_role]:
            raise HTTPException(
                status_code=403,
                detail=f"Permisos insuficientes para este tablero. Se requiere rol '{min_role.value}'",
            )

        return BoardAuthContext(user=current_user, board=board, project=project, role=user_role)

    return _dependency
