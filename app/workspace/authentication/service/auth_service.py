"""
AuthService — Lógica de negocio para registro, autenticación, sesiones y recuperación de cuentas.
Completamente desacoplado de proyectos y diagramas.
"""
import base64
import json
import uuid
import secrets
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.core.security import (
    hash_password,
    verify_password,
    create_jwt_token,
    decode_jwt_token,
    create_password_reset_token,
    verify_password_reset_token,
)
from app.core.session_store import SessionStore
from app.core.email.email_service import EmailService
from app.workspace.authentication.entity.user_entity import User
from app.workspace.authentication.repository.user_repository import UserRepository
from app.workspace.authentication.exception.auth_exceptions import (
    InvalidCredentialsException,
    UserAlreadyExistsException,
    UserNotFoundException,
    InvalidTokenException,
    TokenExpiredException,
)

ACCESS_TOKEN_TTL = 3600  # 1 hora
REFRESH_TOKEN_TTL = 604800  # 7 días


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def _issue_token_pair(self, user: User) -> tuple[str, str]:
        """Emite un access_token y un refresh_token rotativo, registrando la sesión en SessionStore."""
        access_token = create_jwt_token(
            {"sub": user.id, "email": user.email, "purpose": "access"},
            custom_expiration=ACCESS_TOKEN_TTL,
        )

        refresh_jti = secrets.token_hex(16)
        refresh_token = create_jwt_token(
            {"sub": user.id, "jti": refresh_jti, "purpose": "refresh"},
            custom_expiration=REFRESH_TOKEN_TTL,
        )

        await SessionStore.store_refresh_token(user.id, refresh_jti, ttl_seconds=REFRESH_TOKEN_TTL)
        return access_token, refresh_token

    async def register_user(self, full_name: str, email: str, password: str) -> tuple[User, str, str]:
        clean_email = email.strip().lower()
        existing = await self.user_repo.get_by_email(clean_email)
        if existing:
            raise UserAlreadyExistsException("El email ya se encuentra registrado")

        try:
            user = await self.user_repo.create(
                full_name=full_name.strip(),
                email=clean_email,
                password_hash=hash_password(password),
            )
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise UserAlreadyExistsException("El email ya se encuentra registrado")
        except Exception:
            await self.db.rollback()
            raise

        access_token, refresh_token = await self._issue_token_pair(user)
        return user, access_token, refresh_token

    async def authenticate_user(self, email: str, password: str) -> tuple[User, str, str]:
        clean_email = email.strip().lower()
        user = await self.user_repo.get_by_email(clean_email)
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsException("Credenciales incorrectas")

        access_token, refresh_token = await self._issue_token_pair(user)
        return user, access_token, refresh_token

    async def refresh_session(self, refresh_token_str: str) -> tuple[User, str, str]:
        payload = decode_jwt_token(refresh_token_str)
        if not payload or payload.get("purpose") != "refresh":
            raise InvalidTokenException("Refresh token inválido")

        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            raise InvalidTokenException("Estructura de token inválida")

        is_valid = await SessionStore.is_refresh_token_valid(user_id, jti)
        if not is_valid:
            raise TokenExpiredException("El refresh token ha expirado o ya fue utilizado")

        # Rotación estricta de refresh token (invalida el token anterior)
        await SessionStore.revoke_refresh_token(user_id, jti)

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundException("Usuario no encontrado")

        new_access_token, new_refresh_token = await self._issue_token_pair(user)
        return user, new_access_token, new_refresh_token

    async def logout(self, user_id: str, refresh_token_str: str | None = None) -> None:
        if refresh_token_str:
            payload = decode_jwt_token(refresh_token_str)
            if payload and "jti" in payload:
                await SessionStore.revoke_refresh_token(user_id, payload["jti"])
                return
        # Si no se pasó un token específico, revoca todas las sesiones
        await SessionStore.revoke_all_user_sessions(user_id)

    async def update_profile(self, user_id: str, full_name: str | None = None, avatar_url: str | None = None) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundException("Usuario no encontrado")

        updates = {}
        if full_name is not None:
            updates["full_name"] = full_name.strip()
        if avatar_url is not None:
            updates["avatar_url"] = avatar_url.strip() if avatar_url else None

        if updates:
            await self.user_repo.update(user, **updates)
            await self.db.commit()
            await self.db.refresh(user)

        return user

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundException("Usuario no encontrado")

        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsException("La contraseña actual es incorrecta")

        new_hash = hash_password(new_password)
        await self.user_repo.update(user, password_hash=new_hash)
        await self.db.commit()

        # Invalida todas las sesiones de refresco activas por seguridad
        await SessionStore.revoke_all_user_sessions(user_id)

    async def request_password_reset(self, email: str) -> None:
        clean_email = email.strip().lower()
        user = await self.user_repo.get_by_email(clean_email)
        # Prevención de enumeración de usuarios: si no existe, no falla
        if not user:
            return

        token = create_password_reset_token(
            user_id=user.id,
            email=user.email,
            current_password_hash=user.password_hash,
            expiration_seconds=900,  # 15 minutos
        )

        await EmailService.send_password_reset_email(
            to_email=user.email,
            user_name=user.full_name,
            reset_token=token,
        )

    async def reset_password(self, token: str, new_password: str) -> None:
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidTokenException("Formato de token de reseteo inválido")

        try:
            rem = len(parts[1]) % 4
            pad = parts[1] + ("=" * (4 - rem) if rem > 0 else "")
            payload_unverified = json.loads(base64.urlsafe_b64decode(pad.encode("utf-8")).decode("utf-8"))
            user_id = payload_unverified.get("sub")
        except Exception:
            raise InvalidTokenException("Token de reseteo malformado")

        if not user_id:
            raise InvalidTokenException("Token sin identificador de usuario")

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundException("Usuario no encontrado")

        # Verifica la firma criptográfica combinada con la huella del password_hash actual
        payload = verify_password_reset_token(token, user.password_hash)
        if not payload:
            raise TokenExpiredException("El enlace de restablecimiento es inválido, ya fue utilizado o ha expirado")

        new_hash = hash_password(new_password)
        await self.user_repo.update(user, password_hash=new_hash)
        await self.db.commit()

        # Al cambiar el password_hash, cualquier intento posterior de usar el mismo token fallará automáticamente.
        # Además cerramos todas las sesiones activas:
        await SessionStore.revoke_all_user_sessions(user.id)
