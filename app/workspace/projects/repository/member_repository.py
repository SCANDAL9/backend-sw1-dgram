"""
Repositorio para operaciones de base de datos sobre la entidad ProjectMember.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.workspace.projects.entity.project_entity import ProjectMember, ProjectRole
from app.workspace.authentication.entity.user_entity import User


class MemberRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_members(self, project_id: str) -> list[tuple[ProjectMember, User]]:
        stmt = (
            select(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
        )
        result = await self.db.execute(stmt)
        return result.all()

    async def get_member(self, project_id: str, user_id: str) -> ProjectMember | None:
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def add_or_update_member(self, project_id: str, user_id: str, role: ProjectRole) -> ProjectMember:
        pm = await self.get_member(project_id, user_id)
        if pm:
            pm.role = role
        else:
            pm = ProjectMember(project_id=project_id, user_id=user_id, role=role)
            self.db.add(pm)
        await self.db.flush()
        await self.db.refresh(pm)
        return pm

    async def remove_member(self, project_id: str, user_id: str) -> bool:
        stmt = delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0
