"""
Mappers para diagramas y tableros (CU3).
"""
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.dto.board_dto import BoardCreate


def board_to_summary_dict(board: Board) -> dict:
    return {
        "id": board.id,
        "name": board.name,
        "project_id": board.project_id,
        "owner_id": board.owner_id,
        "created_at": str(board.created_at) if board.created_at else None,
        "updated_at": str(board.updated_at) if board.updated_at else None,
    }
