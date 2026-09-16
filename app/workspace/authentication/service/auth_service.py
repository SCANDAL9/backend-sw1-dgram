"""
AuthService — Lógica de negocio para registro y autenticación de usuarios.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import hash_password, verify_password, create_jwt_token, decode_jwt_token
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import Project, ProjectMember
from app.modeling.diagram.entity.board_entity import Board
from app.workspace.authentication.repository.user_repository import UserRepository
from app.workspace.authentication.exception.auth_exceptions import (
    InvalidCredentialsException,
    UserAlreadyExistsException,
)


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def register_user(self, full_name: str, email: str, password: str) -> User:
        clean_email = email.strip().lower()
        existing = await self.user_repo.get_by_email(clean_email)
        if existing:
            raise UserAlreadyExistsException("El email ya se encuentra registrado")

        user = await self.user_repo.create(
            full_name=full_name.strip(),
            email=clean_email,
            password_hash=hash_password(password),
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def authenticate_user(self, email: str, password: str) -> User:
        clean_email = email.strip().lower()
        user = await self.user_repo.get_by_email(clean_email)
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsException("Credenciales incorrectas")
        return user


# Funciones helper para compatibilidad directa
async def register_user(db: AsyncSession, full_name: str, email: str, password: str) -> User:
    service = AuthService(db)
    try:
        return await service.register_user(full_name=full_name, email=email, password=password)
    except UserAlreadyExistsException as e:
        raise ValueError(e.detail)


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    service = AuthService(db)
    try:
        return await service.authenticate_user(email=email, password=password)
    except InvalidCredentialsException:
        return None


async def check_board_access(db: AsyncSession, board_id: str, user_id: str) -> tuple[bool, str]:
    """
    Verifica acceso a un board. Retorna (allowed: bool, role: 'owner'|'editor'|'viewer'|'public').
    """
    if board_id in ("new", "default-board", "default"):
        return True, "owner"

    board = await db.get(Board, board_id)
    if not board:
        return True, "owner"

    if board.owner_id == user_id or board.owner_id == "system" or not board.owner_id:
        return True, "owner"

    if not board.project_id:
        return True, "editor"

    proj = await db.get(Project, board.project_id)
    if proj and proj.owner_id == user_id:
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

