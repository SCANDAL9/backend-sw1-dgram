"""
Controller / Router para Proyectos y Colaboración (CU2).
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, or_
from app.core.database import get_db
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole, ProjectMemory
from app.workspace.authentication.entity.user_entity import User
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.service.relational_mutator_service import ensure_project_and_package
from app.core.websocket.manager import manager

from app.core.dependencies import (
    require_project_role,
    require_board_access,
    get_current_user,
    get_current_user_optional,
    ProjectAuthContext,
    BoardAuthContext,
    DEMO_OWNERS,
)
from app.workspace.projects.dto.project_dto import (
    MemberInvite,
    MemberRoleUpdate,
    MemberResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ProjectBoardCreate,
    ProjectBoardResponse,
    ProjectMemoryCreate,
    ProjectMemoryResponse,
)

router = APIRouter()


@router.get("/projects/{project_id}/members", response_model=list[MemberResponse])
async def list_project_members(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    stmt = (
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        MemberResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=pm.role.value if hasattr(pm.role, "value") else str(pm.role),
            joined_at=str(pm.joined_at) if pm.joined_at else None,
        )
        for pm, user in rows
    ]


@router.post("/projects/{project_id}/members/invite", response_model=MemberResponse)
async def invite_project_member(
    project_id: str,
    data: MemberInvite,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.owner)),
):
    clean_email = data.email.strip().lower()
    user_stmt = select(User).where(User.email == clean_email)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if not user:
        user = User(
            email=clean_email,
            full_name=clean_email.split("@")[0].capitalize(),
            password_hash=None,
        )
        db.add(user)
        await db.flush()

    pm_stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
    )
    pm_res = await db.execute(pm_stmt)
    pm = pm_res.scalar_one_or_none()

    if pm:
        pm.role = data.role
    else:
        pm = ProjectMember(
            project_id=project_id,
            user_id=user.id,
            role=data.role,
        )
        db.add(pm)

    await db.commit()
    await db.refresh(pm)

    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=pm.role.value if hasattr(pm.role, "value") else str(pm.role),
        joined_at=str(pm.joined_at) if pm.joined_at else None,
    )


@router.delete("/projects/{project_id}/members/{user_id}")
async def remove_project_member(
    project_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    if auth.role != ProjectRole.owner and auth.user.id != user_id:
        raise HTTPException(status_code=403, detail="Solo el owner puede expulsar a otros miembros")

    if user_id == auth.project.owner_id:
        raise HTTPException(status_code=400, detail="El owner principal no puede ser eliminado del proyecto")

    stmt = delete(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
    )
    res = await db.execute(stmt)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Miembro no encontrado")

    # Expulsar de los websockets de todos los boards asociados al proyecto
    boards_res = await db.execute(select(Board.id).where(Board.project_id == project_id))
    for b_id in boards_res.scalars().all():
        await manager.kick_user(b_id, user_id, "Membresía del proyecto revocada")

    return {"status": "removed"}


@router.put("/projects/{project_id}/members/{user_id}", response_model=MemberResponse)
async def update_project_member_role(
    project_id: str,
    user_id: str,
    data: MemberRoleUpdate,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.owner)),
):
    if user_id == auth.project.owner_id and data.role != ProjectRole.owner:
        raise HTTPException(status_code=400, detail="No se puede cambiar el rol del owner principal")

    stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
    )
    res = await db.execute(stmt)
    pm = res.scalar_one_or_none()
    if not pm:
        raise HTTPException(status_code=404, detail="Miembro no encontrado")

    pm.role = data.role
    await db.commit()
    await db.refresh(pm)

    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    return MemberResponse(
        user_id=user.id if user else user_id,
        email=user.email if user else "",
        full_name=user.full_name if user else "",
        role=pm.role.value if hasattr(pm.role, "value") else str(pm.role),
        joined_at=str(pm.joined_at) if pm.joined_at else None,
    )


@router.get("/boards/{board_id}/members", response_model=list[MemberResponse])
async def list_board_members(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    board = auth.board
    project_id, _ = await ensure_project_and_package(db, board)
    await db.commit()
    return await list_project_members(project_id, db, auth=ProjectAuthContext(user=auth.user, project=auth.project or board, role=auth.role))


@router.post("/boards/{board_id}/members/invite", response_model=MemberResponse)
async def invite_board_member(
    board_id: str,
    data: MemberInvite,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.owner)),
):
    board = auth.board
    project_id, _ = await ensure_project_and_package(db, board)
    await db.commit()
    return await invite_project_member(project_id, data, db=db, auth=ProjectAuthContext(user=auth.user, project=auth.project or board, role=auth.role))


@router.put("/boards/{board_id}/members/{user_id}", response_model=MemberResponse)
async def update_board_member_role(
    board_id: str,
    user_id: str,
    data: MemberRoleUpdate,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.owner)),
):
    board = auth.board
    project_id, _ = await ensure_project_and_package(db, board)
    await db.commit()
    return await update_project_member_role(
        project_id,
        user_id,
        data,
        db=db,
        auth=ProjectAuthContext(user=auth.user, project=auth.project or board, role=auth.role),
    )


@router.delete("/boards/{board_id}/members/{user_id}")
async def remove_board_member(
    board_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    board = auth.board
    project_id, _ = await ensure_project_and_package(db, board)
    await db.commit()
    res = await remove_project_member(
        project_id,
        user_id,
        db=db,
        auth=ProjectAuthContext(user=auth.user, project=auth.project or board, role=auth.role),
    )
    await manager.kick_user(board_id, user_id, "Acceso revocado del tablero")
    return res


# Catálogo de clases y utilidades de proyecto
class AttributeSummary(BaseModel):
    id: str
    name: str
    data_type: str
    visibility: str
    is_pkey: bool


class ProjectClassResponse(BaseModel):
    id: str
    name: str
    package_id: str
    element_type: str
    is_abstract: bool
    attributes: list[AttributeSummary]
    boards_count: int
    is_on_current_board: bool = False


class AttachClassRequest(BaseModel):
    x: float = 120.0
    y: float = 120.0


@router.get("/projects/{project_id}/classes", response_model=list[ProjectClassResponse])
async def list_project_classes(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    from app.modeling.diagram.entity.uml_entity import Package, ClassElement, Attribute
    from app.modeling.diagram.entity.board_normalized_entity import BoardElement

    stmt = (
        select(ClassElement)
        .join(Package, ClassElement.package_id == Package.id)
        .where(Package.project_id == project_id)
        .order_by(ClassElement.name)
    )
    res = await db.execute(stmt)
    classes = res.scalars().all()

    result = []
    for cls in classes:
        attr_stmt = select(Attribute).where(Attribute.class_id == cls.id).order_by(Attribute.order_index)
        attr_res = await db.execute(attr_stmt)
        attrs = attr_res.scalars().all()

        be_stmt = select(func.count(BoardElement.id)).where(BoardElement.class_id == cls.id)
        be_cnt_res = await db.execute(be_stmt)
        boards_cnt = be_cnt_res.scalar_one_or_none() or 0

        result.append(
            ProjectClassResponse(
                id=cls.id,
                name=cls.name,
                package_id=cls.package_id,
                element_type=cls.element_type.value if hasattr(cls.element_type, "value") else str(cls.element_type),
                is_abstract=cls.is_abstract,
                attributes=[
                    AttributeSummary(
                        id=a.id,
                        name=a.name,
                        data_type=a.data_type,
                        visibility=a.visibility.value if hasattr(a.visibility, "value") else str(a.visibility),
                        is_pkey=a.is_pkey,
                    )
                    for a in attrs
                ],
                boards_count=boards_cnt,
                is_on_current_board=False,
            )
        )
    return result


@router.get("/boards/{board_id}/project-classes", response_model=list[ProjectClassResponse])
async def list_board_project_classes(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
):
    board = auth.board
    project_id, _ = await ensure_project_and_package(db, board)
    await db.commit()

    all_classes = await list_project_classes(
        project_id, db, auth=ProjectAuthContext(user=auth.user, project=auth.project or board, role=auth.role)
    )

    from app.modeling.diagram.entity.board_normalized_entity import BoardElement
    be_stmt = select(BoardElement.class_id).where(BoardElement.board_id == board_id)
    be_res = await db.execute(be_stmt)
    board_class_ids = set(be_res.scalars().all())

    for cls in all_classes:
        cls.is_on_current_board = cls.id in board_class_ids

    return all_classes


@router.post("/boards/{board_id}/attach-class/{class_id}")
@router.post("/boards/{board_id}/classes/{class_id}/attach")
async def attach_class_to_board(
    board_id: str,
    class_id: str,
    req: AttachClassRequest = AttachClassRequest(),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    from app.modeling.diagram.entity.uml_entity import ClassElement, Package
    from app.modeling.diagram.entity.board_normalized_entity import BoardElement

    cls = await db.get(ClassElement, class_id)
    if not cls:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    # Validar que la clase pertenezca al mismo proyecto del tablero (Resource Isolation / Anti-IDOR)
    board = auth.board
    project_id, _ = await ensure_project_and_package(db, board)
    pkg = await db.get(Package, cls.package_id)
    if not pkg or pkg.project_id != project_id:
        raise HTTPException(status_code=403, detail="La clase no pertenece al proyecto de este tablero")

    be_stmt = select(BoardElement).where(
        BoardElement.board_id == board_id,
        BoardElement.class_id == class_id,
    )
    be_res = await db.execute(be_stmt)
    existing_be = be_res.scalar_one_or_none()
    if existing_be:
        return {
            "status": "already_attached",
            "board_element_id": existing_be.id,
            "x": existing_be.x,
            "y": existing_be.y,
        }

    be_id = str(uuid.uuid4())
    new_be = BoardElement(
        id=be_id,
        board_id=board_id,
        class_id=class_id,
        x=req.x,
        y=req.y,
        width=180.0,
        height=120.0,
    )
    db.add(new_be)
    await db.commit()

    return {
        "status": "attached",
        "board_element_id": be_id,
        "class_id": class_id,
        "x": req.x,
        "y": req.y,
    }


@router.delete("/boards/{board_id}/classes/{class_id}/detach")
async def detach_class_from_board(
    board_id: str,
    class_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    from app.modeling.diagram.entity.board_normalized_entity import BoardElement
    await db.execute(
        delete(BoardElement).where(
            BoardElement.board_id == board_id,
            BoardElement.class_id == class_id,
        )
    )
    await db.commit()
    return {"status": "detached", "class_id": class_id, "board_id": board_id}


@router.delete("/boards/{board_id}/classes/{class_id}/model")
async def delete_class_from_board_model(
    board_id: str,
    class_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
):
    from app.modeling.diagram.entity.uml_entity import ClassElement
    from app.modeling.diagram.entity.board_normalized_entity import BoardElement

    cls = await db.get(ClassElement, class_id)
    if not cls:
        return {"status": "not_found", "class_id": class_id}

    await db.execute(delete(BoardElement).where(BoardElement.class_id == class_id))
    await db.execute(delete(ClassElement).where(ClassElement.id == class_id))
    await db.commit()
    return {"status": "deleted_from_model", "class_id": class_id}


@router.delete("/projects/{project_id}/classes/{class_id}")
async def delete_class_from_project_model(
    project_id: str,
    class_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
):
    from app.modeling.diagram.entity.uml_entity import ClassElement
    from app.modeling.diagram.entity.board_normalized_entity import BoardElement

    cls = await db.get(ClassElement, class_id)
    if not cls:
        return {"status": "not_found", "class_id": class_id}

    await db.execute(delete(BoardElement).where(BoardElement.class_id == class_id))
    await db.execute(delete(ClassElement).where(ClassElement.id == class_id))
    await db.commit()
    return {"status": "deleted_from_project", "class_id": class_id}


# CRUD de Proyectos
@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    search: str | None = Query(None, description="Filtrar por nombre o descripción"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # Proyectos demo / públicos visibles para invitados y cualquier usuario registrado
    demo_stmt = select(Project).where(Project.owner_id.in_(DEMO_OWNERS))
    if search:
        search_filter = f"%{search.strip()}%"
        demo_stmt = demo_stmt.where(
            or_(Project.name.ilike(search_filter), Project.description.ilike(search_filter))
        )
    demo_res = await db.execute(demo_stmt)
    demo_projects = demo_res.scalars().all()

    owned_projects = []
    member_rows = []

    if user:
        owned_stmt = select(Project).where(Project.owner_id == user.id)
        if search:
            search_filter = f"%{search.strip()}%"
            owned_stmt = owned_stmt.where(
                or_(Project.name.ilike(search_filter), Project.description.ilike(search_filter))
            )
        owned_res = await db.execute(owned_stmt)
        owned_projects = owned_res.scalars().all()

        member_stmt = (
            select(Project, ProjectMember.role)
            .join(ProjectMember, Project.id == ProjectMember.project_id)
            .where(ProjectMember.user_id == user.id)
        )
        if search:
            search_filter = f"%{search.strip()}%"
            member_stmt = member_stmt.where(
                or_(Project.name.ilike(search_filter), Project.description.ilike(search_filter))
            )
        member_res = await db.execute(member_stmt)
        member_rows = member_res.all()

    seen_ids = set()
    result = []

    for p in demo_projects:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            result.append(
                ProjectResponse(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    owner_id=p.owner_id,
                    my_role="owner",
                    created_at=str(p.created_at) if p.created_at else None,
                    updated_at=str(p.updated_at) if p.updated_at else None,
                )
            )

    for p in owned_projects:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            result.append(
                ProjectResponse(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    owner_id=p.owner_id,
                    my_role="owner",
                    created_at=str(p.created_at) if p.created_at else None,
                    updated_at=str(p.updated_at) if p.updated_at else None,
                )
            )

    for p, role in member_rows:
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            result.append(
                ProjectResponse(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    owner_id=p.owner_id,
                    my_role=role.value if hasattr(role, "value") else str(role),
                    created_at=str(p.created_at) if p.created_at else None,
                    updated_at=str(p.updated_at) if p.updated_at else None,
                )
            )

    return result


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj_id = str(uuid.uuid4())
    project = Project(
        id=proj_id,
        name=data.name,
        description=data.description,
        owner_id=user.id,
    )
    db.add(project)
    await db.flush()

    member = ProjectMember(
        project_id=proj_id,
        user_id=user.id,
        role=ProjectRole.owner,
    )
    db.add(member)

    await db.commit()
    await db.refresh(project)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        my_role="owner",
        created_at=str(project.created_at),
        updated_at=str(project.updated_at) if project.updated_at else None,
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    return ProjectResponse(
        id=auth.project.id,
        name=auth.project.name,
        description=auth.project.description,
        owner_id=auth.project.owner_id,
        my_role=auth.role.value if hasattr(auth.role, "value") else str(auth.role),
        created_at=str(auth.project.created_at) if auth.project.created_at else None,
        updated_at=str(auth.project.updated_at) if auth.project.updated_at else None,
    )


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
):
    project = auth.project
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description

    await db.commit()
    await db.refresh(project)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        my_role=auth.role.value if hasattr(auth.role, "value") else str(auth.role),
        created_at=str(project.created_at) if project.created_at else None,
        updated_at=str(project.updated_at) if project.updated_at else None,
    )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.owner)),
):
    await db.delete(auth.project)
    await db.commit()
    return {"status": "deleted", "id": project_id}


# Boards del proyecto
@router.get("/projects/{project_id}/boards", response_model=list[ProjectBoardResponse])
async def list_project_boards(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    stmt = (
        select(Board)
        .where(Board.project_id == project_id)
        .order_by(Board.created_at.asc())
    )
    result = await db.execute(stmt)
    boards = result.scalars().all()
    return [
        ProjectBoardResponse(
            id=b.id,
            name=b.name,
            project_id=b.project_id,
            owner_id=b.owner_id,
            created_at=str(b.created_at) if b.created_at else None,
            updated_at=str(b.updated_at) if b.updated_at else None,
        )
        for b in boards
    ]


@router.post("/projects/{project_id}/boards", response_model=ProjectBoardResponse)
async def create_project_board(
    project_id: str,
    data: ProjectBoardCreate,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
):
    new_board_id = str(uuid.uuid4())
    board = Board(
        id=new_board_id,
        name=data.name,
        project_id=project_id,
        owner_id=auth.user.id,
    )
    db.add(board)
    await db.flush()

    await ensure_project_and_package(db, board)
    await db.commit()
    await db.refresh(board)

    return ProjectBoardResponse(
        id=board.id,
        name=board.name,
        project_id=board.project_id,
        owner_id=board.owner_id,
        created_at=str(board.created_at) if board.created_at else None,
        updated_at=str(board.updated_at) if board.updated_at else None,
    )


# Project Memory (Directivas arquitectónicas)
@router.get("/projects/{project_id}/memory", response_model=list[ProjectMemoryResponse])
@router.get("/projects/{project_id}/memories", response_model=list[ProjectMemoryResponse])
async def get_project_memory(
    project_id: str,
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    stmt = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
    if category:
        stmt = stmt.where(ProjectMemory.category == category)
    stmt = stmt.order_by(ProjectMemory.created_at.asc())

    res = await db.execute(stmt)
    memories = res.scalars().all()
    return [
        ProjectMemoryResponse(
            id=m.id,
            project_id=m.project_id,
            category=m.category,
            directive=m.directive,
            created_at=str(m.created_at) if m.created_at else None,
            created_by=m.created_by,
        )
        for m in memories
    ]


@router.post("/projects/{project_id}/memory", response_model=ProjectMemoryResponse)
@router.post("/projects/{project_id}/memories", response_model=ProjectMemoryResponse)
async def add_project_memory(
    project_id: str,
    data: ProjectMemoryCreate,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
):
    mem = ProjectMemory(
        id=str(uuid.uuid4()),
        project_id=project_id,
        category=data.category,
        directive=data.directive,
        created_by=auth.user.id,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return ProjectMemoryResponse(
        id=mem.id,
        project_id=mem.project_id,
        category=mem.category,
        directive=mem.directive,
        created_at=str(mem.created_at) if mem.created_at else None,
        created_by=mem.created_by,
    )


@router.delete("/projects/{project_id}/memory/{memory_id}")
@router.delete("/projects/{project_id}/memories/{memory_id}")
async def delete_project_memory(
    project_id: str,
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
):
    mem = await db.get(ProjectMemory, memory_id)
    if not mem or mem.project_id != project_id:
        raise HTTPException(status_code=404, detail="Directiva de memoria no encontrada")
    await db.delete(mem)
    await db.commit()
    return {"status": "deleted", "id": memory_id}

