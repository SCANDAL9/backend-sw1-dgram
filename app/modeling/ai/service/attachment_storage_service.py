"""
attachment_storage_service.py — Servicio de almacenamiento de archivos adjuntos multimedia para el chat.
"""
from pathlib import Path
from app.core.config import BASE_DIR

STORAGE_DIR = BASE_DIR / "storage" / "attachments"

MIME_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
}


def save_attachment_file(board_id: str, attachment_id: str, data: bytes, mime_type: str) -> str:
    ext = MIME_EXT_MAP.get(mime_type.lower().split(";")[0].strip(), ".bin")
    board_dir = STORAGE_DIR / board_id
    board_dir.mkdir(parents=True, exist_ok=True)
    file_path = board_dir / f"{attachment_id}{ext}"
    file_path.write_bytes(data)
    return f"/api/chat/boards/{board_id}/attachments/{attachment_id}"


def get_attachment_file_path(board_id: str, attachment_id: str) -> Path | None:
    board_dir = STORAGE_DIR / board_id
    if not board_dir.exists():
        return None
    for item in board_dir.glob(f"{attachment_id}.*"):
        if item.is_file():
            return item
    return None
