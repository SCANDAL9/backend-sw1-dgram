"""
Controller / Router para Proyectos y Colaboración (CU2).
Arquitectura limpia: controlador delgado (Thin Controller) que delega en ProjectService.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.workspace.projects.entity.project_entity import ProjectRole
from app.workspace.authentication.entity.user_entity import User
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
    ProjectClassResponse,
    AttachClassRequest,
    ProjectMemoryCreate,
    ProjectMemoryResponse,
)
from app.workspace.projects.service.project_service import ProjectService

router = APIRouter()


def get_project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


# --- MIEMBROS DE PROYECTO ---
@router.get("/projects/{project_id}/members", response_model=list[MemberResponse])
async def list_project_members(
    project_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.list_members(project_id)


@router.post("/projects/{project_id}/members/invite", response_model=MemberResponse)
async def invite_project_member(
    project_id: str,
    data: MemberInvite,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.owner)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.invite_member(project_id, data.email, data.role)


@router.delete("/projects/{project_id}/members/{user_id}")
async def remove_project_member(
    project_id: str,
    user_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    await service.remove_member(
        project=auth.project,
        auth_user_id=auth.user.id,
        auth_role=auth.role,
        target_user_id=user_id,
    )
    return {"status": "removed"}


@router.put("/projects/{project_id}/members/{user_id}", response_model=MemberResponse)
async def update_project_member_role(
    project_id: str,
    user_id: str,
    data: MemberRoleUpdate,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.owner)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.update_member_role(auth.project, user_id, data.role)


# --- MIEMBROS A NIVEL DE TABLERO (HEREDADOS DEL PROYECTO) ---
@router.get("/boards/{board_id}/members", response_model=list[MemberResponse])
async def list_board_members(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    project_id, _ = await ensure_project_and_package(db, auth.board)
    await db.commit()
    return await service.list_members(project_id)


@router.post("/boards/{board_id}/members/invite", response_model=MemberResponse)
async def invite_board_member(
    board_id: str,
    data: MemberInvite,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.owner)),
    service: ProjectService = Depends(get_project_service),
):
    project_id, _ = await ensure_project_and_package(db, auth.board)
    await db.commit()
    return await service.invite_member(project_id, data.email, data.role)


@router.put("/boards/{board_id}/members/{user_id}", response_model=MemberResponse)
async def update_board_member_role(
    board_id: str,
    user_id: str,
    data: MemberRoleUpdate,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.owner)),
    service: ProjectService = Depends(get_project_service),
):
    project_id, _ = await ensure_project_and_package(db, auth.board)
    await db.commit()
    target_project = auth.project or auth.board
    return await service.update_member_role(target_project, user_id, data.role)


@router.delete("/boards/{board_id}/members/{user_id}")
async def remove_board_member(
    board_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    project_id, _ = await ensure_project_and_package(db, auth.board)
    await db.commit()
    target_project = auth.project or auth.board
    await service.remove_member(
        project=target_project,
        auth_user_id=auth.user.id,
        auth_role=auth.role,
        target_user_id=user_id,
    )
    await manager.kick_user(board_id, user_id, "Acceso revocado del tablero")
    return {"status": "removed"}


# --- CATÁLOGO DE CLASES UML ---
@router.get("/projects/{project_id}/classes", response_model=list[ProjectClassResponse])
async def list_project_classes(
    project_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.list_project_classes(project_id)


@router.get("/boards/{board_id}/project-classes", response_model=list[ProjectClassResponse])
async def list_board_project_classes(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    project_id, _ = await ensure_project_and_package(db, auth.board)
    await db.commit()
    return await service.list_board_project_classes(auth.board, project_id)


@router.post("/boards/{board_id}/attach-class/{class_id}")
@router.post("/boards/{board_id}/classes/{class_id}/attach")
async def attach_class_to_board(
    board_id: str,
    class_id: str,
    req: AttachClassRequest = AttachClassRequest(),
    db: AsyncSession = Depends(get_db),
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    project_id, _ = await ensure_project_and_package(db, auth.board)
    return await service.attach_class_to_board(auth.board, project_id, class_id, req.x, req.y)


@router.delete("/boards/{board_id}/classes/{class_id}/detach")
async def detach_class_from_board(
    board_id: str,
    class_id: str,
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.detach_class_from_board(board_id, class_id)


@router.delete("/boards/{board_id}/classes/{class_id}/model")
async def delete_class_from_board_model(
    board_id: str,
    class_id: str,
    auth: BoardAuthContext = Depends(require_board_access(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.delete_class_from_model(class_id)


@router.delete("/projects/{project_id}/classes/{class_id}")
async def delete_class_from_project_model(
    project_id: str,
    class_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    res = await service.delete_class_from_model(class_id)
    if res.get("status") == "deleted_from_model":
        return {"status": "deleted_from_project", "class_id": class_id}
    return res


# --- CRUD DE PROYECTOS ---
@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    search: str | None = Query(None, description="Filtrar por nombre o descripción"),
    limit: int | None = Query(None, ge=1, le=100, description="Límite de resultados"),
    offset: int | None = Query(None, ge=0, description="Desplazamiento para paginación"),
    user: User | None = Depends(get_current_user_optional),
    service: ProjectService = Depends(get_project_service),
):
    return await service.list_projects(user, search, DEMO_OWNERS, limit=limit, offset=offset)


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    return await service.create_project(data.name, user.id, data.description)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
):
    role_str = auth.role.value if hasattr(auth.role, "value") else str(auth.role)
    return ProjectResponse(
        id=auth.project.id,
        name=auth.project.name,
        description=auth.project.description,
        owner_id=auth.project.owner_id,
        my_role=role_str,
        created_at=str(auth.project.created_at) if auth.project.created_at else None,
        updated_at=str(auth.project.updated_at) if auth.project.updated_at else None,
    )


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    role_str = auth.role.value if hasattr(auth.role, "value") else str(auth.role)
    return await service.update_project(auth.project, data.name, data.description, role_str)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.owner)),
    service: ProjectService = Depends(get_project_service),
):
    await service.delete_project(auth.project)
    return {"status": "deleted", "id": project_id}


# --- TABLEROS (BOARDS) DEL PROYECTO ---
@router.get("/projects/{project_id}/boards", response_model=list[ProjectBoardResponse])
async def list_project_boards(
    project_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.list_project_boards(project_id)


@router.post("/projects/{project_id}/boards", response_model=ProjectBoardResponse)
async def create_project_board(
    project_id: str,
    data: ProjectBoardCreate,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.create_project_board(project_id, data.name, auth.user.id)


# --- DIRECTIVAS DE MEMORIA ARQUITECTÓNICA ---
@router.get("/projects/{project_id}/memory", response_model=list[ProjectMemoryResponse])
@router.get("/projects/{project_id}/memories", response_model=list[ProjectMemoryResponse])
async def get_project_memory(
    project_id: str,
    category: str | None = Query(None),
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.viewer)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.list_project_memories(project_id, category)


@router.post("/projects/{project_id}/memory", response_model=ProjectMemoryResponse)
@router.post("/projects/{project_id}/memories", response_model=ProjectMemoryResponse)
async def add_project_memory(
    project_id: str,
    data: ProjectMemoryCreate,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.add_project_memory(project_id, data.category, data.directive, auth.user.id)


@router.delete("/projects/{project_id}/memory/{memory_id}")
@router.delete("/projects/{project_id}/memories/{memory_id}")
async def delete_project_memory(
    project_id: str,
    memory_id: str,
    auth: ProjectAuthContext = Depends(require_project_role(ProjectRole.editor)),
    service: ProjectService = Depends(get_project_service),
):
    return await service.delete_project_memory(project_id, memory_id)
