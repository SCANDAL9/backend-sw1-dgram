"""
Guide Repository — Data access layer for spatial AI guide sessions.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.ai.entity.guide_entity import GuideSession


class GuideRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_board_and_token(
        self,
        board_id: str,
        session_token: str,
    ) -> GuideSession | None:
        stmt = (
            select(GuideSession)
            .where(
                GuideSession.board_id == board_id,
                GuideSession.session_token == session_token,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_session(
        self,
        board_id: str,
        session_token: str,
        user_id: str | None = None,
    ) -> GuideSession:
        session = GuideSession(
            board_id=board_id,
            session_token=session_token,
            user_id=user_id,
            completed_steps=[],
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session
