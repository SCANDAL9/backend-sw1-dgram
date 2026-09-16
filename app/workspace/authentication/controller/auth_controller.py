"""
Controller / Router para autenticación (CU1).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import create_jwt_token
from app.workspace.authentication.dto.auth_dto import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserProfile,
)
from app.workspace.authentication.service.auth_service import AuthService
from app.workspace.authentication.entity.user_entity import User
from app.workspace.authentication.mapper.user_mapper import user_to_profile_dto
from app.workspace.authentication.exception.auth_exceptions import (
    UserAlreadyExistsException,
    InvalidCredentialsException,
)
from app.core.dependencies import get_current_user

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user = await service.register_user(
            full_name=data.full_name, email=data.email, password=data.password
        )
    except UserAlreadyExistsException as e:
        raise HTTPException(status_code=400, detail=e.detail)

    token = create_jwt_token({"sub": user.id, "email": user.email})
    return TokenResponse(
        access_token=token,
        user=user_to_profile_dto(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user = await service.authenticate_user(email=data.email, password=data.password)
    except InvalidCredentialsException as e:
        raise HTTPException(status_code=401, detail=e.detail)

    token = create_jwt_token({"sub": user.id, "email": user.email})
    return TokenResponse(
        access_token=token,
        user=user_to_profile_dto(user),
    )


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    return user_to_profile_dto(user)
