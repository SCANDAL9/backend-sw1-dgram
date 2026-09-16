"""
Persistencia de estado binario Yjs (CRDT) para tableros dgram.
Almacena y recupera snapshots Y.Doc en formato BYTEA en PostgreSQL.
"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.modeling.diagram.entity.board_entity import Board


async def load_ydoc_state(db: AsyncSession, board_id: str) -> bytes | None:
    """Carga el snapshot binario del Y.Doc de un tablero si existe."""
    result = await db.execute(
        select(Board.yjs_state).where(Board.id == board_id)
    )
    return result.scalar_one_or_none()


async def save_ydoc_state(db: AsyncSession, board_id: str, state_bytes: bytes) -> None:
    """Persiste el snapshot binario del Y.Doc en la tabla de tableros."""
    await db.execute(
        update(Board)
        .where(Board.id == board_id)
        .values(yjs_state=state_bytes)
    )
    await db.commit()
