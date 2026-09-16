"""
Mappers para convertir entre Project/ProjectMember Entities y sus DTOs.
"""
from app.workspace.projects.entity.project_entity import Project, ProjectMember, ProjectRole
from app.workspace.authentication.entity.user_entity import User
from app.workspace.projects.dto.project_dto import (
    ProjectResponse,
    MemberResponse,
)


def project_to_response_dto(project: Project, my_role: str | None = None) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        my_role=my_role,
        created_at=str(project.created_at) if project.created_at else None,
        updated_at=str(project.updated_at) if project.updated_at else None,
    )


def member_to_response_dto(pm: ProjectMember, user: User) -> MemberResponse:
    role_val = pm.role.value if hasattr(pm.role, "value") else str(pm.role)
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role_val,
        joined_at=str(pm.joined_at) if pm.joined_at else None,
    )
