"""
Codegen Repository — Accesses normalized diagram states and schemas for code generation.
"""
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.modeling.diagram.entity.board_entity import Board


class CodegenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_board(self, board_id: str) -> Board | None:
        return await self.db.get(Board, board_id)

    async def get_board_state(self, board_id: str) -> dict[str, Any]:
        state = await get_normalized_board_state(self.db, board_id)
        return state or {"entities": [], "relations": []}
