"""
XMI DTOs — Data Transfer Objects for XMI / Enterprise Architect import and export.
"""
from typing import Any
from pydantic import BaseModel, Field


class XmiImportResponse(BaseModel):
    status: str
    message: str
    classes: list[str] = Field(default_factory=list)
    associations_count: int = 0


class XmiClassExportPayload(BaseModel):
    id: str
    name: str
    element_type: str = "class"
    is_abstract: bool = False
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 100.0, "y": 100.0})


class XmiAssociationExportPayload(BaseModel):
    id: str
    sourceId: str
    targetId: str
    type: str = "association"
    name: str | None = None
