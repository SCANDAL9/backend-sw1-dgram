"""
Repositorio para operaciones de base de datos sobre la entidad Project y Board asociadas.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole
from app.workspace.authentication.entity.user_entity import User
from app.modeling.diagram.entity.board_entity import Board


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

    async def list_projects_search(
        self,
        user: User | None,
        search: str | None,
        demo_owners: list[str],
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[tuple[Project, str]]:
        user_id = user.id if user else None
        search_filter = f"%{search.strip()}%" if search and search.strip() else None

        access_conditions = [Project.owner_id.in_(demo_owners)]
        if user_id:
            access_conditions.append(Project.owner_id == user_id)
            access_conditions.append(ProjectMember.user_id == user_id)

        from sqlalchemy import case

        role_expression = case(
            (Project.owner_id == user_id, "owner"),
            (Project.owner_id.in_(demo_owners), "owner"),
            else_=ProjectMember.role,
        ).label("user_role")

        stmt = (
            select(Project, role_expression)
            .outerjoin(
                ProjectMember,
                (Project.id == ProjectMember.project_id) & (ProjectMember.user_id == user_id),
            )
            .where(or_(*access_conditions))
        )

        if search_filter:
            stmt = stmt.where(
                or_(Project.name.ilike(search_filter), Project.description.ilike(search_filter))
            )

        stmt = stmt.order_by(
            Project.updated_at.desc().nullslast(),
            Project.created_at.desc(),
        )

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        res = await self.db.execute(stmt)
        rows = res.all()

        seen_ids = set()
        result: list[tuple[Project, str]] = []
        for p, role in rows:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                role_str = role.value if hasattr(role, "value") else (str(role) if role else "owner")
                result.append((p, role_str))

        return result

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

    async def list_boards(self, project_id: str) -> list[Board]:
        stmt = (
            select(Board)
            .where(Board.project_id == project_id)
            .order_by(Board.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_board(self, project_id: str, name: str, owner_id: str) -> Board:
        new_board_id = str(uuid.uuid4())
        board = Board(
            id=new_board_id,
            name=name,
            project_id=project_id,
            owner_id=owner_id,
        )
        self.db.add(board)
        await self.db.flush()
        return board

    async def get_project_board_ids(self, project_id: str) -> list[str]:
        boards_res = await self.db.execute(select(Board.id).where(Board.project_id == project_id))
        return list(boards_res.scalars().all())
