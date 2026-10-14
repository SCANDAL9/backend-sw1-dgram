"""
ProjectService — Lógica de negocio para gestión de proyectos, miembros, tableros, catálogo y memorias.
"""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole, ProjectMemory
from app.workspace.projects.repository.project_repository import ProjectRepository
from app.workspace.projects.repository.member_repository import MemberRepository
from app.workspace.projects.repository.project_catalog_repository import ProjectCatalogRepository
from app.workspace.projects.repository.project_memory_repository import ProjectMemoryRepository
from app.workspace.authentication.repository.user_repository import UserRepository
from app.workspace.authentication.entity.user_entity import User
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.service.relational_mutator_service import ensure_project_and_package
from app.core.websocket.manager import manager
from app.workspace.projects.dto.project_dto import (
    MemberResponse,
    ProjectResponse,
    ProjectBoardResponse,
    ProjectClassResponse,
    ProjectMemoryResponse,
)
from app.workspace.projects.mapper.project_mapper import project_to_response_dto
from app.workspace.projects.exception.project_exceptions import (
    ProjectNotFoundException,
    MemberNotFoundException,
)


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.member_repo = MemberRepository(db)
        self.user_repo = UserRepository(db)
        self.catalog_repo = ProjectCatalogRepository(db)
        self.memory_repo = ProjectMemoryRepository(db)

    # --- PROYECTOS CRUD Y BÚSQUEDA ---
    async def list_projects(
        self,
        user: User | None,
        search: str | None,
        demo_owners: list[str],
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ProjectResponse]:
        projects_with_roles = await self.project_repo.list_projects_search(
            user, search, demo_owners, limit=limit, offset=offset
        )
        return [project_to_response_dto(p, role) for p, role in projects_with_roles]

    async def create_project(self, name: str, owner_id: str, description: str | None = None) -> ProjectResponse:
        project = await self.project_repo.create(name=name, owner_id=owner_id, description=description)
        await self.member_repo.add_or_update_member(project.id, owner_id, ProjectRole.owner)
        await self.db.commit()
        await self.db.refresh(project)
        return project_to_response_dto(project, "owner")

    async def get_project(self, project_id: str) -> Project:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise ProjectNotFoundException()
        return project

    async def update_project(
        self,
        project: Project,
        name: str | None,
        description: str | None,
        my_role: str,
    ) -> ProjectResponse:
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        await self.db.commit()
        await self.db.refresh(project)
        return project_to_response_dto(project, my_role)

    async def delete_project(self, project: Project) -> None:
        await self.db.delete(project)
        await self.db.commit()

    # --- MIEMBROS ---
    async def list_members(self, project_id: str) -> list[MemberResponse]:
        rows = await self.member_repo.list_members(project_id)
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

    async def invite_member(self, project_id: str, email: str, role: ProjectRole) -> MemberResponse:
        clean_email = email.strip().lower()
        user = await self.user_repo.get_by_email(clean_email)
        if not user:
            user = await self.user_repo.create(
                email=clean_email,
                full_name=clean_email.split("@")[0].capitalize(),
                password_hash=None,
            )
        pm = await self.member_repo.add_or_update_member(project_id, user.id, role)
        await self.db.commit()
        await self.db.refresh(pm)
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=pm.role.value if hasattr(pm.role, "value") else str(pm.role),
            joined_at=str(pm.joined_at) if pm.joined_at else None,
        )

    async def update_member_role(
        self,
        project: Project,
        target_user_id: str,
        new_role: ProjectRole,
    ) -> MemberResponse:
        if target_user_id == project.owner_id and new_role != ProjectRole.owner:
            raise HTTPException(status_code=400, detail="No se puede cambiar el rol del owner principal")

        pm = await self.member_repo.get_member(project.id, target_user_id)
        if not pm:
            raise HTTPException(status_code=404, detail="Miembro no encontrado")

        pm.role = new_role
        await self.db.commit()
        await self.db.refresh(pm)

        user = await self.user_repo.get_by_id(target_user_id)
        return MemberResponse(
            user_id=user.id if user else target_user_id,
            email=user.email if user else "",
            full_name=user.full_name if user else "",
            role=pm.role.value if hasattr(pm.role, "value") else str(pm.role),
            joined_at=str(pm.joined_at) if pm.joined_at else None,
        )

    async def remove_member(
        self,
        project: Project,
        auth_user_id: str,
        auth_role: ProjectRole,
        target_user_id: str,
    ) -> None:
        if auth_role != ProjectRole.owner and auth_user_id != target_user_id:
            raise HTTPException(status_code=403, detail="Solo el owner puede expulsar a otros miembros")

        if target_user_id == project.owner_id:
            raise HTTPException(status_code=400, detail="El owner principal no puede ser eliminado del proyecto")

        removed = await self.member_repo.remove_member(project.id, target_user_id)
        await self.db.commit()
        if not removed:
            raise HTTPException(status_code=404, detail="Miembro no encontrado")

        # Expulsar de los websockets de todos los boards asociados al proyecto
        board_ids = await self.project_repo.get_project_board_ids(project.id)
        for b_id in board_ids:
            await manager.kick_user(b_id, target_user_id, "Membresía del proyecto revocada")

    # --- TABLEROS (BOARDS) ---
    async def list_project_boards(self, project_id: str) -> list[ProjectBoardResponse]:
        boards = await self.project_repo.list_boards(project_id)
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

    async def create_project_board(self, project_id: str, name: str, user_id: str) -> ProjectBoardResponse:
        board = await self.project_repo.create_board(project_id=project_id, name=name, owner_id=user_id)
        await ensure_project_and_package(self.db, board)
        await self.db.commit()
        await self.db.refresh(board)
        return ProjectBoardResponse(
            id=board.id,
            name=board.name,
            project_id=board.project_id,
            owner_id=board.owner_id,
            created_at=str(board.created_at) if board.created_at else None,
            updated_at=str(board.updated_at) if board.updated_at else None,
        )

    # --- CATÁLOGO DE CLASES UML ---
    async def list_project_classes(self, project_id: str) -> list[ProjectClassResponse]:
        return await self.catalog_repo.list_project_classes(project_id)

    async def list_board_project_classes(self, board: Board, project_id: str) -> list[ProjectClassResponse]:
        all_classes = await self.catalog_repo.list_project_classes(project_id)
        board_class_ids = await self.catalog_repo.get_board_class_ids(board.id)
        for cls in all_classes:
            cls.is_on_current_board = cls.id in board_class_ids
        return all_classes

    async def attach_class_to_board(
        self,
        board: Board,
        project_id: str,
        class_id: str,
        x: float,
        y: float,
    ) -> dict:
        cls, pkg = await self.catalog_repo.get_class_with_package(class_id)
        if not cls:
            raise HTTPException(status_code=404, detail="Clase no encontrada")

        if not pkg or pkg.project_id != project_id:
            raise HTTPException(status_code=403, detail="La clase no pertenece al proyecto de este tablero")

        existing_be = await self.catalog_repo.get_board_element(board.id, class_id)
        if existing_be:
            return {
                "status": "already_attached",
                "board_element_id": existing_be.id,
                "x": existing_be.x,
                "y": existing_be.y,
            }

        new_be = await self.catalog_repo.attach_class(board.id, class_id, x, y)
        return {
            "status": "attached",
            "board_element_id": new_be.id,
            "class_id": class_id,
            "x": x,
            "y": y,
        }

    async def detach_class_from_board(self, board_id: str, class_id: str) -> dict:
        await self.catalog_repo.detach_class(board_id, class_id)
        return {"status": "detached", "class_id": class_id, "board_id": board_id}

    async def delete_class_from_model(self, class_id: str) -> dict:
        deleted = await self.catalog_repo.delete_class_from_model(class_id)
        if not deleted:
            return {"status": "not_found", "class_id": class_id}
        return {"status": "deleted_from_model", "class_id": class_id}

    # --- MEMORIAS ARQUITECTÓNICAS ---
    async def list_project_memories(self, project_id: str, category: str | None = None) -> list[ProjectMemoryResponse]:
        memories = await self.memory_repo.list_by_project(project_id, category)
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

    async def add_project_memory(
        self,
        project_id: str,
        category: str,
        directive: str,
        user_id: str,
    ) -> ProjectMemoryResponse:
        mem = await self.memory_repo.create(project_id, category, directive, user_id)
        return ProjectMemoryResponse(
            id=mem.id,
            project_id=mem.project_id,
            category=mem.category,
            directive=mem.directive,
            created_at=str(mem.created_at) if mem.created_at else None,
            created_by=mem.created_by,
        )

    async def delete_project_memory(self, project_id: str, memory_id: str) -> dict:
        mem = await self.memory_repo.get_by_id(memory_id)
        if not mem or mem.project_id != project_id:
            raise HTTPException(status_code=404, detail="Directiva de memoria no encontrada")
        await self.memory_repo.delete(mem)
        return {"status": "deleted", "id": memory_id}
