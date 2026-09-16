"""
Schema Export Entity — Model representation for persisted schema metadata and exports.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExportedSchemaMetadata:
    board_id: str
    board_name: str
    classes_count: int = 0
    associations_count: int = 0
    format: str = "XMI_2_1"
    raw_content: str = ""
