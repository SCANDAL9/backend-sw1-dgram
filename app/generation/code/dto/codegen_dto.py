"""
Codegen DTOs — Schemas for code generation requests and generated file trees.
"""
from pydantic import BaseModel, Field


class GenerateCodeRequest(BaseModel):
    base_package: str = Field(default="com.dgram.generated", description="Paquete base para las clases Java")


class GenerateCodeResponse(BaseModel):
    status: str
    base_package: str
    files_count: int
    files: dict[str, str] = Field(default_factory=dict)
