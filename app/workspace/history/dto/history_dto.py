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
    summary: str | None = None
    target_name: str | None = None


class TimelineFilterDTO(BaseModel):
    actor_id: str | None = None
    actor_type: str | None = None
    command_type: str | None = None
    from_version: int | None = None
    to_version: int | None = None
    limit: int = 50
    offset: int = 0


class HistoryDetailDTO(BaseModel):
    entry: HistoryItemDTO
    diff: dict[str, Any] = {}


class RestoreVersionResponseDTO(BaseModel):
    success: bool
    restored_version: int
    new_diagram_version: int
    message: str


class SnapshotSummaryDTO(BaseModel):
    id: str
    version: int
    created_by: str | None = None

