"""
Codegen Entity — Models representing generated source code bundles and artifacts.
"""
from dataclasses import dataclass, field


@dataclass
class GeneratedProjectBundle:
    base_package: str
    target_framework: str = "Spring Boot 3.3.x (Java 21)"
    files_count: int = 0
    files: dict[str, str] = field(default_factory=dict)
