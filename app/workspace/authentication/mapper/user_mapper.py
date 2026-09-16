"""
Mappers para convertir entre UserEntity y UserProfile/DTOs.
"""
from app.workspace.authentication.entity.user_entity import User
from app.workspace.authentication.dto.auth_dto import UserProfile


def user_to_profile_dto(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        avatar_url=user.avatar_url,
        created_at=str(user.created_at) if user.created_at else None,
    )
