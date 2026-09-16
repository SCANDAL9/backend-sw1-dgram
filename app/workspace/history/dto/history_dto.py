"""
DTOs para consulta de historial, timeline y snapshots (CU7).
"""
from pydantic import BaseModel
from typing import Any


class HistoryItemDTO(BaseModel):
    id: str
    board_id: str
    command_id: str
    command_type: str
    payload: dict[str, Any]
    actor_id: str | None = None
    actor_type: str | None = None
    model_version: int | None = None
    created_at: str | None = None


class TimelineFilterDTO(BaseModel):
    actor_id: str | None = None
    command_type: str | None = None
    from_version: int | None = None
    to_version: int | None = None
