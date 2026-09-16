"""
codegen_service.py — Service orchestrator for generating Java 21 / Spring Boot 3 projects.
"""
from typing import Any
import io
import zipfile
from app.generation.code.service.spring_boot_generator_service import SpringBootGenerator


class CodegenService:
    def __init__(self, base_package: str = "com.dgram.generated"):
        self.base_package = base_package
        self.generator = SpringBootGenerator(base_package=base_package)

    def generate_files(self, diagram_state: dict[str, Any]) -> dict[str, str]:
        return self.generator.generate_project_bundle(diagram_state)

    def generate_zip(self, diagram_state: dict[str, Any]) -> bytes:
        files = self.generate_files(diagram_state)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path, content in files.items():
                zip_file.writestr(file_path, content)
        zip_buffer.seek(0)
        return zip_buffer.getvalue()
