from pydantic import BaseModel, ConfigDict


class BoardCreate(BaseModel):
    name: str
    description: str | None = None
    owner_id: str = ""
    project_id: str | None = None


class BoardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class BoardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    owner_id: str
    project_id: str | None = None
    diagram_version: int = 0
    entities_count: int = 0
    relations_count: int = 0
    preview_entities: list[str] = []
    created_at: str
