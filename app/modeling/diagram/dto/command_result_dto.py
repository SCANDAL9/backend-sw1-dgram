from pydantic import BaseModel


class CommandResult(BaseModel):
    success: bool
    command_id: str
    error: str | None = None
    new_model_version: int = 0
