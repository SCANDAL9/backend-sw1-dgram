"""
Repositorio para operaciones sobre Boards y Snapshots (CU3).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import BoardSnapshot


class BoardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, board_id: str) -> Board | None:
        return await self.db.get(Board, board_id)

    async def list_by_project(self, project_id: str) -> list[Board]:
        stmt = select(Board).where(Board.project_id == project_id).order_by(Board.created_at.asc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_latest_snapshot(self, board_id: str) -> BoardSnapshot | None:
        stmt = (
            select(BoardSnapshot)
            .where(BoardSnapshot.board_id == board_id)
            .order_by(BoardSnapshot.version.desc())
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
