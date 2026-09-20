"""
Controller / Router para autenticación, gestión de cuentas y sesiones (CU1).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.workspace.authentication.dto.auth_dto import (
    UserRegister,
    UserLogin,
    TokenResponse,
    RefreshTokenRequest,
    UserProfile,
    UserProfileUpdate,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    MessageResponse,
)
from app.workspace.authentication.service.auth_service import AuthService
from app.workspace.authentication.entity.user_entity import User
from app.workspace.authentication.mapper.user_mapper import user_to_profile_dto
from app.workspace.authentication.exception.auth_exceptions import (
    UserAlreadyExistsException,
    InvalidCredentialsException,
    UserNotFoundException,
    InvalidTokenException,
    TokenExpiredException,
)
from app.core.dependencies import get_current_user

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user, access_token, refresh_token = await service.register_user(
            full_name=data.full_name, email=data.email, password=data.password
        )
    except UserAlreadyExistsException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_to_profile_dto(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user, access_token, refresh_token = await service.authenticate_user(
            email=data.email, password=data.password
        )
    except InvalidCredentialsException as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.detail)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_to_profile_dto(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user, access_token, refresh_token = await service.refresh_session(data.refresh_token)
    except (InvalidTokenException, TokenExpiredException) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.detail)
    except UserNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.detail)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_to_profile_dto(user),
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    data: RefreshTokenRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    token_str = data.refresh_token if data else None
    await service.logout(user_id=user.id, refresh_token_str=token_str)
    return MessageResponse(message="Sesión cerrada correctamente")


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    return user_to_profile_dto(user)


@router.put("/me", response_model=UserProfile)
async def update_me(
    data: UserProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    updated_user = await service.update_profile(
        user_id=user.id, full_name=data.full_name, avatar_url=data.avatar_url
    )
    return user_to_profile_dto(updated_user)


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    try:
        await service.change_password(
            user_id=user.id,
            current_password=data.current_password,
            new_password=data.new_password,
        )
    except InvalidCredentialsException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail)

    return MessageResponse(message="Contraseña actualizada exitosamente")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    await service.request_password_reset(data.email)
    return MessageResponse(
        message="Si la dirección está registrada, recibirás instrucciones para restablecer tu contraseña."
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        await service.reset_password(token=data.token, new_password=data.new_password)
    except (InvalidTokenException, TokenExpiredException) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail)
    except UserNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.detail)

    return MessageResponse(message="Contraseña restablecida exitosamente. Ya puedes iniciar sesión con tu nueva contraseña.")
