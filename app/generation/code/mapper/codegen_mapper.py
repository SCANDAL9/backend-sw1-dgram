"""
Codegen Mapper — Transforms code generation file maps to DTOs and API responses.
"""
from typing import Any
from app.generation.code.dto.codegen_dto import GenerateCodeResponse


class CodegenMapper:
    @staticmethod
    def to_response(base_package: str, files: dict[str, str]) -> GenerateCodeResponse:
        return GenerateCodeResponse(
            status="success",
            base_package=base_package,
            files_count=len(files),
            files=files,
        )
