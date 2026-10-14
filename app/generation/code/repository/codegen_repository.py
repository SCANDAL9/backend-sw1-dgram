"""
codegen_repository.py — Accesses normalized diagram states, boards, and records history for code generation.
Encapsulates database access and history logging for Spring Boot code generation workflows.
"""
import uuid
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import BoardHistory, ActorTypeEnum
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole
from app.core.dependencies import ROLE_LEVELS


class CodegenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_board(self, board_id: str) -> Optional[Board]:
        """Recupera un tablero por su identificador primario."""
        return await self.db.get(Board, board_id)

    async def get_board_state(self, board_id: str) -> dict[str, Any]:
        """Recupera el estado normalizado reconstruido del tablero."""
        state = await get_normalized_board_state(self.db, board_id)
        return state or {"entities": [], "relations": []}

    async def verify_board_access_for_user(
        self,
        board: Board,
        user: User,
        min_role: ProjectRole = ProjectRole.viewer,
    ) -> None:
        """Verifica que el usuario tenga privilegios para acceder al tablero o su proyecto contenedor."""
        if board.owner_id == user.id or board.owner_id == "system":
            return

        if board.project_id:
            project = await self.db.get(Project, board.project_id)
            if project:
                if project.owner_id == user.id:
                    return
                stmt = select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == user.id,
                )
                res = await self.db.execute(stmt)
                pm = res.scalar_one_or_none()
                if pm and ROLE_LEVELS[pm.role] >= ROLE_LEVELS[min_role]:
                    return

        raise HTTPException(status_code=403, detail="No tienes acceso a este tablero")

    async def record_codegen_history(
        self,
        board_id: str,
        actor_id: Optional[str],
        model_version: Optional[int],
        command_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Registra una entrada de trazabilidad en BoardHistory para auditoría de generación."""
        history_entry = BoardHistory(
            id=str(uuid.uuid4()),
            board_id=board_id,
            command_id=command_id,
            actor_id=actor_id,
            command_type="GENERATE_CODE",
            payload=payload,
            actor_type=ActorTypeEnum.user,
            model_version=model_version,
        )
        self.db.add(history_entry)
        await self.db.commit()
