"""
history_repository.py — Data Access Layer for BoardSnapshots and history queries (CU7).
Encapsulates direct database operations on snapshots and timeline records.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.board_normalized_entity import BoardSnapshot


class HistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_snapshots(
        self, board_id: str, limit: int = 30
    ) -> List[BoardSnapshot]:
        """
        Recupera la lista de snapshots persistidos ordenados por versión descendente.
        """
        stmt = (
            select(BoardSnapshot)
            .where(BoardSnapshot.board_id == board_id)
            .order_by(BoardSnapshot.version.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_snapshot_by_version(
        self, board_id: str, version: int
    ) -> Optional[BoardSnapshot]:
        """
        Recupera un snapshot específico por versión y board_id.
        """
        stmt = (
            select(BoardSnapshot)
            .where(
                BoardSnapshot.board_id == board_id,
                BoardSnapshot.version == version,
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
