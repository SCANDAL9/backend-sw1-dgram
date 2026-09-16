"""
command_history_service.py — Historial durable de comandos respaldado en PostgreSQL (board_history).
Mantiene un log transaccional ordenado por version/timestamp para soporte de undo/redo determinista.
"""
import logging
import uuid
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from app.core.database import async_session_factory
from app.modeling.diagram.entity.board_normalized_entity import BoardHistory, ActorTypeEnum
from app.modeling.diagram.dto.command_dto import Command
from app.modeling.diagram.dto.command_dto import CommandType
from app.modeling.diagram.dto.command_dto import CommandPayload

logger = logging.getLogger(__name__)


class CommandHistory:
    """PostgreSQL-backed command history for durable undo/redo per board."""

    def __init__(self, board_id: str):
        self.board_id = board_id
        self._pointer = -1
        self._cached_commands: list[Command] = []

    async def push(self, command: Command, actor_id: str | None = None) -> None:
        if self._pointer < len(self._cached_commands) - 1:
            self._cached_commands = self._cached_commands[: self._pointer + 1]

        self._cached_commands.append(command)
        self._pointer += 1

        cmd_type_str = (
            command.command_type.value
            if hasattr(command.command_type, "value")
            else str(command.command_type)
        )
        payload_dict = (
            command.payload.model_dump()
            if hasattr(command.payload, "model_dump")
            else dict(command.payload)
        )

        try:
            async with async_session_factory() as session:
                entry = BoardHistory(
                    id=str(uuid.uuid4()),
                    board_id=self.board_id,
                    command_id=command.command_id,
                    command_type=cmd_type_str,
                    payload=payload_dict,
                    actor_id=actor_id,
                    actor_type=ActorTypeEnum.user,
                    model_version=command.model_version,
                )
                session.add(entry)
                await session.commit()
        except IntegrityError:
            logger.debug("Comando %s ya existente en BoardHistory (idempotente)", command.command_id)
        except Exception as e:
            logger.error("Error persistiendo entrada de BoardHistory para board %s: %s", self.board_id, e)


    async def can_undo(self) -> bool:
        return self._pointer >= 0

    async def can_redo(self) -> bool:
        return self._pointer < len(self._cached_commands) - 1

    async def undo(self) -> Command | None:
        if not await self.can_undo():
            return None
        cmd = self._cached_commands[self._pointer]
        self._pointer -= 1
        return cmd

    async def redo(self) -> Command | None:
        if not await self.can_redo():
            return None
        self._pointer += 1
        return self._cached_commands[self._pointer]

    async def get_all(self, upto_pointer: bool = False) -> list[Command]:
        if upto_pointer:
            return self._cached_commands[: self._pointer + 1]
        return list(self._cached_commands)

    async def find_command(self, command_id: str) -> Command | None:
        for cmd in reversed(self._cached_commands):
            if cmd.command_id == command_id:
                return cmd

        async with async_session_factory() as session:
            stmt = select(BoardHistory).where(
                BoardHistory.board_id == self.board_id,
                BoardHistory.command_id == command_id,
            )
            res = await session.execute(stmt)
            entry = res.scalar_one_or_none()
            if entry:
                return Command(
                    command_id=entry.command_id,
                    board_id=entry.board_id,
                    command_type=CommandType(entry.command_type),
                    payload=CommandPayload(**entry.payload),
                    model_version=entry.model_version or 1,
                )
        return None

    async def get_history_entries(self, limit: int = 50) -> list[dict]:
        async with async_session_factory() as session:
            stmt = (
                select(BoardHistory)
                .where(BoardHistory.board_id == self.board_id)
                .order_by(BoardHistory.created_at.desc())
                .limit(limit)
            )
            res = await session.execute(stmt)
            entries = res.scalars().all()
            return [
                {
                    "id": e.id,
                    "command_id": e.command_id,
                    "command_type": e.command_type,
                    "payload": e.payload,
                    "actor_id": e.actor_id,
                    "actor_type": e.actor_type.value if hasattr(e.actor_type, "value") else str(e.actor_type),
                    "model_version": e.model_version,
                    "created_at": str(e.created_at),
                }
                for e in entries
            ]
