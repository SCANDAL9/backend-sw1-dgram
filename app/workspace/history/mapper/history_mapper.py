"""
HistoryMapper — Mapeador de entidades y entradas de historial a DTOs de transporte HTTP (CU7).
"""
from typing import Any
from app.workspace.history.dto.history_dto import (
    HistoryItemDTO,
    HistoryDetailDTO,
    SnapshotSummaryDTO,
    RestoreVersionResponseDTO,
)
from app.modeling.diagram.entity.board_normalized_entity import BoardSnapshot


class HistoryMapper:
    @staticmethod
    def dict_to_item_dto(data: dict[str, Any]) -> HistoryItemDTO:
        return HistoryItemDTO(**data)

    @staticmethod
    def dict_to_detail_dto(data: dict[str, Any]) -> HistoryDetailDTO:
        return HistoryDetailDTO(**data)

    @staticmethod
    def snapshot_to_summary_dto(snapshot: BoardSnapshot) -> SnapshotSummaryDTO:
        return SnapshotSummaryDTO(
            id=snapshot.id,
            version=snapshot.version,
            created_by=snapshot.created_by,
        )

    @staticmethod
    def dict_to_restore_response_dto(data: dict[str, Any]) -> RestoreVersionResponseDTO:
        return RestoreVersionResponseDTO(**data)
