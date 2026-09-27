"""
dependencies.py — Dependencias centralizadas de autenticación y autorización RBAC para FastAPI.
"""
from dataclasses import dataclass
from typing import Callable
from fastapi import Depends, HTTPException, Header, Path, Query
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
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extrae y valida el JWT del header Authorization: Bearer <token> o del parámetro query token."""
    auth_header = authorization
    if not auth_header and token:
        auth_header = f"Bearer {token}"
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token de autorización requerido")
    raw_token = auth_header.split(" ")[1]
    payload = auth_service.decode_jwt_token(raw_token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


async def get_current_user_optional(
    authorization: str | None = Header(None),
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Extrae el usuario si se suministra un token válido (header o query param); de lo contrario retorna None."""
    from app.main import app
    if get_current_user in app.dependency_overrides:
        override = app.dependency_overrides[get_current_user]
        if callable(override):
            import inspect
            sig = inspect.signature(override)
            kwargs = {}
            if "db" in sig.parameters:
                kwargs["db"] = db
            if "authorization" in sig.parameters:
                kwargs["authorization"] = authorization
            if "token" in sig.parameters:
                kwargs["token"] = token
            if inspect.iscoroutinefunction(override):
                return await override(**kwargs)
            return override(**kwargs)
    auth_header = authorization
    if not auth_header and token:
        auth_header = f"Bearer {token}"
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    raw_token = auth_header.split(" ")[1]
    payload = auth_service.decode_jwt_token(raw_token)
    if not payload or "sub" not in payload:
        return None
    return await db.get(User, payload["sub"])


DEMO_OWNERS = {"system", "user-test", "demo", "public", "00000000-0000-0000-0000-000000000001"}


def require_project_role(min_role: ProjectRole = ProjectRole.viewer) -> Callable:
    """Fábrica de dependencias para validar acceso y rol en un proyecto."""
    async def _dependency(
        project_id: str = Path(...),
        current_user: User | None = Depends(get_current_user_optional),
        db: AsyncSession = Depends(get_db),
    ) -> ProjectAuthContext:
        project = await db.get(Project, project_id)
        if not project:
            if not current_user:
                raise HTTPException(status_code=401, detail="Token de autorización requerido")
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")

        # Proyectos demo / públicos permiten acceso de owner a invitados y cualquier usuario
        if project.owner_id in DEMO_OWNERS:
            effective_user = current_user or User(id="guest", full_name="Invitado", email="guest@dgram.local")
            return ProjectAuthContext(user=effective_user, project=project, role=ProjectRole.owner)

        if not current_user:
            raise HTTPException(status_code=401, detail="Token de autorización requerido")

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
        current_user: User | None = Depends(get_current_user_optional),
        db: AsyncSession = Depends(get_db),
    ) -> BoardAuthContext:
        board = await db.get(Board, board_id)
        if not board:
            if not current_user:
                raise HTTPException(status_code=401, detail="Token de autorización requerido")
            raise HTTPException(status_code=404, detail="Board not found")

        project = None
        user_role = None

        # Tableros demo / públicos permiten acceso de owner tanto a invitados como a registrados
        if board.owner_id in DEMO_OWNERS:
            user_role = ProjectRole.owner

        if board.project_id:
            project = await db.get(Project, board.project_id)
            if project and project.owner_id in DEMO_OWNERS:
                user_role = ProjectRole.owner

        if current_user:
            if board.owner_id == current_user.id:
                user_role = ProjectRole.owner

            if board.project_id and project:
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
                        if not user_role or ROLE_LEVELS[pm.role] > ROLE_LEVELS[user_role]:
                            user_role = pm.role

        if not user_role:
            if not current_user:
                raise HTTPException(status_code=401, detail="Token de autorización requerido")
            raise HTTPException(status_code=403, detail="No tienes acceso a este tablero")

        if ROLE_LEVELS[user_role] < ROLE_LEVELS[min_role]:
            raise HTTPException(
                status_code=403,
                detail=f"Permisos insuficientes para este tablero. Se requiere rol '{min_role.value}'",
            )

        effective_user = current_user or User(id="guest", full_name="Invitado", email="guest@dgram.local")
        return BoardAuthContext(user=effective_user, board=board, project=project, role=user_role)

    return _dependency
