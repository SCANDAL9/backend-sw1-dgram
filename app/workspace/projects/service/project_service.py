"""
ProjectService — Lógica de negocio para gestión de proyectos y miembros.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole
from app.workspace.projects.repository.project_repository import ProjectRepository
from app.workspace.projects.repository.member_repository import MemberRepository
from app.workspace.authentication.repository.user_repository import UserRepository
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

    async def list_user_projects(self, user_id: str) -> list[tuple[Project, str]]:
        return await self.project_repo.list_for_user(user_id)

    async def create_project(self, name: str, owner_id: str, description: str | None = None) -> Project:
        project = await self.project_repo.create(name=name, owner_id=owner_id, description=description)
        # Añadir al dueño como miembro con rol 'owner'
        await self.member_repo.add_or_update_member(project.id, owner_id, ProjectRole.owner)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def get_project(self, project_id: str) -> Project:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise ProjectNotFoundException()
        return project

    async def update_project(self, project_id: str, name: str | None = None, description: str | None = None) -> Project:
        project = await self.get_project(project_id)
        await self.project_repo.update(project, name=name, description=description)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def delete_project(self, project_id: str) -> None:
        project = await self.get_project(project_id)
        await self.project_repo.delete(project)
        await self.db.commit()

    async def list_members(self, project_id: str):
        return await self.member_repo.list_members(project_id)

    async def invite_member(self, project_id: str, email: str, role: ProjectRole):
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
        return pm, user

    async def change_role(self, project_id: str, target_user_id: str, new_role: ProjectRole):
        pm = await self.member_repo.get_member(project_id, target_user_id)
        if not pm:
            raise MemberNotFoundException()
        pm.role = new_role
        await self.db.commit()
        await self.db.refresh(pm)
        user = await self.user_repo.get_by_id(target_user_id)
        return pm, user

    async def remove_member(self, project_id: str, target_user_id: str):
        removed = await self.member_repo.remove_member(project_id, target_user_id)
        if not removed:
            raise MemberNotFoundException()
        await self.db.commit()
        return True
