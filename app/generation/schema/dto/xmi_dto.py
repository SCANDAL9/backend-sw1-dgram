"""
XMI DTOs — Data Transfer Objects for XMI / Enterprise Architect import and export.
"""
from typing import Any
from pydantic import BaseModel, Field


class XmiImportResponse(BaseModel):
    status: str
    message: str
    classes: list[str] = Field(default_factory=list)
    updated_classes: list[str] = Field(default_factory=list)
    associations_count: int = 0


class XmiClassExportPayload(BaseModel):
    id: str
    name: str
    element_type: str = "class"
    is_abstract: bool = False
    external_ref: str | None = None
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 100.0, "y": 100.0})


class XmiAssociationExportPayload(BaseModel):
    id: str
    sourceId: str
    targetId: str
    type: str = "association"
    name: str | None = None
    source_role: str | None = None
    target_role: str | None = None
    source_multiplicity: str | None = None
    target_multiplicity: str | None = None


class XmiPreviewClassDTO(BaseModel):
    name: str
    external_ref: str | None = None
    element_type: str = "class"
    is_abstract: bool = False
    attributes_count: int = 0
    attributes: list[str] = Field(default_factory=list)
    action: str = "create"  # "create" | "update"


class XmiPreviewAssociationDTO(BaseModel):
    type: str
    source_name: str
    target_name: str
    name: str | None = None
    source_role: str | None = None
    target_role: str | None = None
    source_multiplicity: str | None = None
    target_multiplicity: str | None = None


class XmiPreviewResponseDTO(BaseModel):
    total_classes: int
    classes_to_create: list[XmiPreviewClassDTO] = Field(default_factory=list)
    classes_to_update: list[XmiPreviewClassDTO] = Field(default_factory=list)
    associations: list[XmiPreviewAssociationDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
