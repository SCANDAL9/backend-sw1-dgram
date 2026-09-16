"""
Repositorio para operaciones de base de datos sobre la entidad Project.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole


class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, project_id: str) -> Project | None:
        return await self.db.get(Project, project_id)

    async def list_for_user(self, user_id: str) -> list[tuple[Project, str]]:
        # Proyectos propios
        owned_stmt = select(Project).where(Project.owner_id == user_id)
        owned_res = await self.db.execute(owned_stmt)
        owned_projects = owned_res.scalars().all()

        # Proyectos como miembro
        member_stmt = (
            select(Project, ProjectMember.role)
            .join(ProjectMember, Project.id == ProjectMember.project_id)
            .where(ProjectMember.user_id == user_id)
        )
        member_res = await self.db.execute(member_stmt)
        member_rows = member_res.all()

        seen_ids = set()
        projects_with_roles: list[tuple[Project, str]] = []

        for p in owned_projects:
            seen_ids.add(p.id)
            projects_with_roles.append((p, "owner"))

        for p, role in member_rows:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                role_str = role.value if hasattr(role, "value") else str(role)
                projects_with_roles.append((p, role_str))

        return projects_with_roles

    async def create(self, name: str, owner_id: str, description: str | None = None) -> Project:
        project = Project(
            name=name,
            owner_id=owner_id,
            description=description,
        )
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def update(self, project: Project, **kwargs) -> Project:
        for key, value in kwargs.items():
            if hasattr(project, key) and value is not None:
                setattr(project, key, value)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def delete(self, project: Project) -> None:
        await self.db.delete(project)
        await self.db.flush()
