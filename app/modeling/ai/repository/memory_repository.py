"""
Memory Repository — Data access for Project Memory Bank directivas and conventions.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.workspace.projects.entity.project_entity import ProjectMemory
from app.modeling.diagram.entity.board_entity import Board


class MemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_project(self, project_id: str) -> list[ProjectMemory]:
        stmt = (
            select(ProjectMemory)
            .where(ProjectMemory.project_id == project_id)
            .order_by(ProjectMemory.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_board(self, board_id: str) -> list[ProjectMemory]:
        board = await self.db.get(Board, board_id)
        if not board or not getattr(board, "project_id", None):
            return []
        return await self.get_by_project(str(board.project_id))

    async def add(
        self,
        project_id: str,
        directive: str,
        category: str = "convention",
        user_id: str | None = None,
    ) -> ProjectMemory:
        memory = ProjectMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            category=category,
            directive=directive.strip(),
            created_by=user_id,
        )
        self.db.add(memory)
        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    async def delete(self, memory_id: str) -> bool:
        memory = await self.db.get(ProjectMemory, memory_id)
        if not memory:
            return False
        await self.db.delete(memory)
        await self.db.commit()
        return True
