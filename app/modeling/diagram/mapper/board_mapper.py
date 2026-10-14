"""
Mappers para convertir entre Board Entity y BoardResponse DTO.
"""
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.dto.board_dto import BoardResponse


def board_to_response_dto(
    board: Board,
    entities_count: int = 0,
    relations_count: int = 0,
    preview_entities: list[str] | None = None,
) -> BoardResponse:
    """Convierte una entidad Board a BoardResponse DTO."""
    return BoardResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        owner_id=board.owner_id,
        project_id=board.project_id,
        diagram_version=board.diagram_version or 0,
        entities_count=entities_count,
        relations_count=relations_count,
        preview_entities=preview_entities or [],
        created_at=str(board.created_at) if board.created_at else None,
    )
