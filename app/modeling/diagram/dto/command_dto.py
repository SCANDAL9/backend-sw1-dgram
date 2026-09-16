from uuid import uuid4
from datetime import datetime, timezone
from pydantic import BaseModel
from app.modeling.diagram.dto.command_type_dto import CommandType
from app.modeling.diagram.dto.command_payload_dto import CommandPayload
from app.modeling.diagram.dto.command_result_dto import CommandResult


class Command(BaseModel):
    command_id: str = ""
    command_type: CommandType
    payload: CommandPayload
    actor: str = ""
    timestamp: str = ""
    model_version: int = 0

    def __init__(self, **data):
        if not data.get("command_id"):
            data["command_id"] = str(uuid4())
        if not data.get("timestamp"):
            data["timestamp"] = datetime.now(timezone.utc).isoformat()
        super().__init__(**data)
