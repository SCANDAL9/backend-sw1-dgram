"""
Repositorio para operaciones de base de datos sobre la entidad User.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.workspace.authentication.entity.user_entity import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, full_name: str, email: str, password_hash: str | None = None, avatar_url: str | None = None) -> User:
        user = User(
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            avatar_url=avatar_url,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def update(self, user: User, **kwargs) -> User:
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        await self.db.flush()
        await self.db.refresh(user)
        return user
