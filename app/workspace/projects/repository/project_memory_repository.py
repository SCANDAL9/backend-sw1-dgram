"""
Repositorio para operaciones sobre ProjectMemory (directivas arquitectónicas).
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.workspace.projects.entity.project_entity import ProjectMemory


class ProjectMemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_project(self, project_id: str, category: str | None = None) -> list[ProjectMemory]:
        stmt = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
        if category:
            stmt = stmt.where(ProjectMemory.category == category)
        stmt = stmt.order_by(ProjectMemory.created_at.asc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_by_id(self, memory_id: str) -> ProjectMemory | None:
        return await self.db.get(ProjectMemory, memory_id)

    async def create(self, project_id: str, category: str, directive: str, created_by: str) -> ProjectMemory:
        mem = ProjectMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            category=category,
            directive=directive,
            created_by=created_by,
        )
        self.db.add(mem)
        await self.db.commit()
        await self.db.refresh(mem)
        return mem

    async def delete(self, mem: ProjectMemory) -> None:
        await self.db.delete(mem)
        await self.db.commit()
