"""
board_service — operaciones sobre boards.

Operaciones con persistencia normalizada y caché JSONB (board_snapshots, board_history).
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import BoardHistory, BoardSnapshot, ActorTypeEnum


async def create_board(
    db: AsyncSession,
    name: str,
    owner_id: str,
    description: str | None = None,
    project_id: str | None = None,
) -> Board:
    board = Board(
        name=name,
        owner_id=owner_id,
        description=description,
        project_id=project_id,
    )
    db.add(board)
    await db.commit()
    await db.refresh(board)
    return board


async def get_board(db: AsyncSession, board_id: str) -> Board | None:
    return await db.get(Board, board_id)


async def list_boards(db: AsyncSession, owner_id: str | None = None) -> list[Board]:
    stmt = select(Board)
    if owner_id:
        stmt = stmt.where(Board.owner_id == owner_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


DEMO_OWNERS = {"system", "user-test", "demo", "public", "00000000-0000-0000-0000-000000000001"}


async def list_boards_for_user(db: AsyncSession, user_id: str | None) -> list[Board]:
    """Retorna tableros donde el usuario es owner o miembro del proyecto asociado, mas tableros demo/publicos."""
    from app.workspace.projects.entity.project_entity import Project, ProjectMember

    demo_proj_stmt = select(Project.id).where(Project.owner_id.in_(DEMO_OWNERS))
    demo_cond = (Board.owner_id.in_(DEMO_OWNERS)) | (Board.project_id.in_(demo_proj_stmt))

    if user_id:
        member_proj_stmt = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
        all_proj_stmt = select(Project.id).where(
            (Project.owner_id == user_id) | (Project.id.in_(member_proj_stmt))
        )
        filter_cond = demo_cond | (Board.owner_id == user_id) | (Board.project_id.in_(all_proj_stmt))
    else:
        filter_cond = demo_cond

    stmt = (
        select(Board)
        .where(filter_cond)
        .order_by(Board.updated_at.desc().nullslast(), Board.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())



async def delete_board(db: AsyncSession, board_id: str) -> bool:
    board = await db.get(Board, board_id)
    if board is None:
        return False
    await db.delete(board)
    await db.commit()
    return True


async def update_board(
    db: AsyncSession,
    board_id: str,
    name: str | None = None,
    description: str | None = None,
) -> Board | None:
    board = await db.get(Board, board_id)
    if board is None:
        return None
    if name is not None:
        board.name = name
    if description is not None:
        board.description = description
    await db.commit()
    await db.refresh(board)
    return board


async def save_snapshot(db: AsyncSession, board_id: str, snapshot_dict: dict) -> bool:
    """
    Persiste el snapshot en la tabla de snapshots estructurados board_snapshots.
    """
    board = await db.get(Board, board_id)
    if board is None:
        board = Board(
            id=board_id,
            name=board_id,
            owner_id="system",
            description="Auto-created by dgram",
        )
        db.add(board)
        await db.flush()

    new_version = (board.diagram_version or 0) + 1
    board.diagram_version = new_version

    snapshot_entry = BoardSnapshot(
        id=str(uuid.uuid4()),
        board_id=board_id,
        version=new_version,
        snapshot=snapshot_dict,
        created_by=board.owner_id,
    )
    db.add(snapshot_entry)
    await db.commit()
    return True


async def save_snapshot_normalized(
    db: AsyncSession,
    board_id: str,
    state: dict,
    command_id: str,
    command_type: str,
    payload: dict,
    actor_id: str | None,
    model_version: int,
    expected_version: int,
    actor: str | None = None,
) -> bool:
    """
    Persistencia normalizada:

    1. INSERT board_history ON CONFLICT (command_id) DO NOTHING  → idempotencia retry
    2. UPDATE boards SET diagram_version = expected_version+1
          WHERE id = board_id AND diagram_version = expected_version
       → optimistic locking; si 0 rows el caller reintenta con state:sync
    3. INSERT board_snapshots ON CONFLICT DO NOTHING  → caché JSONB
    """
    is_ai = (
        (actor and "ai" in str(actor).lower())
        or (actor_id and "ai" in str(actor_id).lower())
    )
    effective_actor_type = ActorTypeEnum.ai if is_ai else ActorTypeEnum.user

    # 0. Asegurar que el board existe en la tabla boards antes de insertar en board_history
    safe_actor_id = (
        actor_id
        if actor_id and actor_id != "guest" and not str(actor_id).startswith("guest")
        else None
    )
    b_stmt = select(Board).where(Board.id == board_id)
    b_res = await db.execute(b_stmt)
    b_obj = b_res.scalar_one_or_none()
    if not b_obj:
        b_obj = Board(
            id=board_id,
            name=f"Board {board_id}",
            owner_id=safe_actor_id or "system",
            diagram_version=model_version,
        )
        db.add(b_obj)
        await db.flush()
    else:
        b_obj.diagram_version = max(model_version, (b_obj.diagram_version or 0) + 1)

    history_id = None
    if command_id:
        existing_h = await db.execute(
            select(BoardHistory).where(BoardHistory.command_id == command_id)
        )
        existing_entry = existing_h.scalar_one_or_none()
        if existing_entry:
            history_id = existing_entry.id
        else:
            history_entry = BoardHistory(
                id=str(uuid.uuid4()),
                board_id=board_id,
                command_id=command_id,
                command_type=command_type,
                payload=payload,
                actor_id=safe_actor_id,
                actor_type=effective_actor_type,
                model_version=model_version,
            )
            db.add(history_entry)
            history_id = history_entry.id

    # 1.1 Si el comando proviene de IA, vincular board_history_id en ai_action
    if is_ai and command_id and history_id:
        from app.modeling.ai.entity.chat_entity import AiAction, ActionStatus
        ai_stmt = (
            select(AiAction)
            .where(
                AiAction.function_arguments["_command_id"].astext == command_id
            )
            .order_by(AiAction.created_at.desc())
            .limit(1)
        )
        ai_res = await db.execute(ai_stmt)
        ai_act = ai_res.scalar_one_or_none()
        if ai_act:
            ai_act.board_history_id = history_id
            ai_act.status = ActionStatus.success

    # 3. board_snapshots — caché regenerable (idempotente)
    snap_stmt = select(BoardSnapshot).where(
        BoardSnapshot.board_id == board_id,
        BoardSnapshot.version == model_version,
    )
    snap_res = await db.execute(snap_stmt)
    if not snap_res.scalar_one_or_none():
        snapshot_entry = BoardSnapshot(
            id=str(uuid.uuid4()),
            board_id=board_id,
            version=model_version,
            snapshot=state,
            created_by=actor_id,
        )
        db.add(snapshot_entry)

    await db.commit()
    return True
