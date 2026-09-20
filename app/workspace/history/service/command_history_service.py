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


def format_command_summary(cmd_type: str, payload: dict) -> tuple[str, str | None]:
    """Generates a human-friendly summary and target name from command payload."""
    c_type = str(cmd_type).upper()
    if c_type in ("CREATE_ENTITY", "CREATE_CLASS"):
        name = payload.get("entity_name") or payload.get("class_name") or "Clase"
        st = payload.get("stereotype") or payload.get("element_type")
        st_text = f" «{st}»" if st and st != "class" else ""
        return f"Clase{st_text} creada: '{name}'", str(name)
    if c_type in ("DELETE_ENTITY", "DELETE_CLASS"):
        name = payload.get("entity_name") or payload.get("class_name") or payload.get("entity_id") or "Clase"
        return f"Clase eliminada: '{name}'", str(name)
    if c_type in ("MOVE_ENTITY", "MOVE_CLASS"):
        name = payload.get("entity_name") or payload.get("class_name") or payload.get("entity_id") or "Elemento"
        pos = payload.get("position", {})
        pos_str = f"({int(pos.get('x', 0))}, {int(pos.get('y', 0))})" if pos else ""
        return f"Clase reposicionada {pos_str}", str(name)
    if c_type in ("UPDATE_ENTITY", "RENAME_ENTITY"):
        name = payload.get("new_name") or payload.get("entity_name") or payload.get("name") or "Clase"
        return f"Clase actualizada: '{name}'", str(name)
    if c_type in ("ADD_COLUMN", "ADD_ATTRIBUTE"):
        col = payload.get("column") or {}
        col_name = col.get("name") or payload.get("attribute_name") or payload.get("name") or "atributo"
        col_type = col.get("type") or payload.get("data_type") or ""
        type_str = f": {col_type}" if col_type else ""
        return f"Atributo añadido: '{col_name}{type_str}'", str(col_name)
    if c_type in ("DELETE_COLUMN", "DELETE_ATTRIBUTE"):
        name = payload.get("column_name") or payload.get("attribute_id") or "atributo"
        return f"Atributo eliminado: '{name}'", str(name)
    if c_type in ("UPDATE_COLUMN", "UPDATE_ATTRIBUTE"):
        name = payload.get("column_name") or payload.get("name") or "atributo"
        return f"Atributo modificado: '{name}'", str(name)
    if c_type in ("CREATE_RELATION", "CREATE_ASSOCIATION"):
        rel_type = payload.get("type") or "Asociación"
        return f"Relación creada: {rel_type}", str(rel_type)
    if c_type in ("DELETE_RELATION", "DELETE_ASSOCIATION"):
        return "Relación eliminada", None
    if c_type in ("UPDATE_RELATION", "UPDATE_ASSOCIATION"):
        return "Relación modificada", None
    if c_type == "RESTORE_VERSION":
        v = payload.get("restored_from_version", "?")
        return f"Diagrama restaurado a versión {v}", f"v{v}"
    return f"Operación: {cmd_type}", None


class CommandHistory:
    """PostgreSQL-backed command history for durable undo/redo per board."""

    def __init__(self, board_id: str, db: AsyncSession | None = None):
        self.board_id = board_id
        self.db = db
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

        is_ai = (
            (command.actor and "ai" in str(command.actor).lower())
            or (actor_id and "ai" in str(actor_id).lower())
        )
        effective_actor_type = ActorTypeEnum.ai if is_ai else ActorTypeEnum.user

        try:
            async with async_session_factory() as session:
                entry = BoardHistory(
                    id=str(uuid.uuid4()),
                    board_id=self.board_id,
                    command_id=command.command_id,
                    command_type=cmd_type_str,
                    payload=payload_dict,
                    actor_id=actor_id,
                    actor_type=effective_actor_type,
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

    async def get_history_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        actor_type: str | None = None,
        command_type: str | None = None,
        from_version: int | None = None,
        to_version: int | None = None,
    ) -> list[dict]:
        if self.db is not None:
            return await self._query_history_entries(
                self.db, limit, offset, actor_type, command_type, from_version, to_version
            )
        async with async_session_factory() as session:
            return await self._query_history_entries(
                session, limit, offset, actor_type, command_type, from_version, to_version
            )

    async def _query_history_entries(
        self,
        session: AsyncSession,
        limit: int,
        offset: int,
        actor_type: str | None,
        command_type: str | None,
        from_version: int | None,
        to_version: int | None,
    ) -> list[dict]:
        stmt = select(BoardHistory).where(BoardHistory.board_id == self.board_id)

        if actor_type:
            a_type = actor_type.strip().lower()
            if a_type == "ai":
                stmt = stmt.where(BoardHistory.actor_type == ActorTypeEnum.ai)
            elif a_type == "user":
                stmt = stmt.where(BoardHistory.actor_type == ActorTypeEnum.user)

        if command_type:
            c_clean = command_type.strip().upper()
            stmt = stmt.where(BoardHistory.command_type.ilike(f"%{c_clean}%"))

        if from_version is not None:
            stmt = stmt.where(BoardHistory.model_version >= from_version)
        if to_version is not None:
            stmt = stmt.where(BoardHistory.model_version <= to_version)

        stmt = stmt.order_by(
            BoardHistory.model_version.desc(),
            BoardHistory.created_at.desc(),
        ).offset(offset).limit(limit)

        res = await session.execute(stmt)
        entries = res.scalars().all()

        result = []
        for e in entries:
            summary, target_name = format_command_summary(e.command_type, e.payload)
            result.append({
                "id": e.id,
                "board_id": e.board_id,
                "command_id": e.command_id,
                "command_type": e.command_type,
                "payload": e.payload,
                "actor_id": e.actor_id,
                "actor_type": e.actor_type.value if hasattr(e.actor_type, "value") else str(e.actor_type),
                "model_version": e.model_version,
                "created_at": str(e.created_at),
                "summary": summary,
                "target_name": target_name,
            })
        return result

    async def get_entry_detail(self, history_id: str) -> dict | None:
        if self.db is not None:
            return await self._query_entry_detail(self.db, history_id)
        async with async_session_factory() as session:
            return await self._query_entry_detail(session, history_id)

    async def _query_entry_detail(self, session: AsyncSession, history_id: str) -> dict | None:
        stmt = select(BoardHistory).where(
            BoardHistory.board_id == self.board_id,
            BoardHistory.id == history_id,
        )
        res = await session.execute(stmt)
        entry = res.scalar_one_or_none()
        if not entry:
            return None

        summary, target_name = format_command_summary(entry.command_type, entry.payload)
        item = {
            "id": entry.id,
            "board_id": entry.board_id,
            "command_id": entry.command_id,
            "command_type": entry.command_type,
            "payload": entry.payload,
            "actor_id": entry.actor_id,
            "actor_type": entry.actor_type.value if hasattr(entry.actor_type, "value") else str(entry.actor_type),
            "model_version": entry.model_version,
            "created_at": str(entry.created_at),
            "summary": summary,
            "target_name": target_name,
        }

        # Build readable diff summary
        changes = []
        p = entry.payload or {}
        for k, v in p.items():
            if k not in ("board_id", "command_id"):
                changes.append({"field": k, "value": v})

        return {
            "entry": item,
            "diff": {
                "summary": summary,
                "target_name": target_name,
                "fields_changed": len(changes),
                "changes": changes,
            },
        }


