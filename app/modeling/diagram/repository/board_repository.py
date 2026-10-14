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

    async def get_latest_snapshots_batch(self, board_ids: list[str]) -> dict[str, BoardSnapshot]:
        """Obtiene el último snapshot para cada board_id en una sola consulta SQL."""
        if not board_ids:
            return {}
        stmt = (
            select(BoardSnapshot)
            .distinct(BoardSnapshot.board_id)
            .where(BoardSnapshot.board_id.in_(board_ids))
            .order_by(BoardSnapshot.board_id, BoardSnapshot.version.desc())
        )
        res = await self.db.execute(stmt)
        return {s.board_id: s for s in res.scalars().all()}
