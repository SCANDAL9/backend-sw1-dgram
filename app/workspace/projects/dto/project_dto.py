"""
DTOs para proyectos y miembros colaboradores (CU2).
"""
from pydantic import BaseModel
from app.workspace.projects.entity.project_entity import ProjectRole


class MemberInvite(BaseModel):
    email: str
    role: ProjectRole = ProjectRole.editor


class MemberRoleUpdate(BaseModel):
    role: ProjectRole


class MemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    joined_at: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    owner_id: str
    my_role: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectBoardCreate(BaseModel):
    name: str = "Main Diagram"


class ProjectBoardResponse(BaseModel):
    id: str
    name: str
    project_id: str
    owner_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProjectMemoryCreate(BaseModel):
    category: str = "convention"
    directive: str


class ProjectMemoryResponse(BaseModel):
    id: str
    project_id: str
    category: str
    directive: str
    created_at: str | None = None
    created_by: str | None = None


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
    boards_count: int = 0
    is_on_current_board: bool = False


class AttachClassRequest(BaseModel):
    x: float = 120.0
    y: float = 120.0
