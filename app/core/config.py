from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BASE_DIR.parent / ".env"), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base de Datos & Caché 
    database_url: str
    redis_url: str
    ws_history_limit: int
    cors_origins: str

    # Feature flags & entorno 
    use_normalized_reads: bool
    dev_mode: bool

    # Seguridad & Autenticación JWT 
    jwt_secret_key: str
    jwt_expiration_seconds: int

    # Google Cloud Vertex AI 
    gcp_project_id: str | None
    gcp_location: str | None
    google_application_credentials: str | None
    vertex_model_name: str | None


@lru_cache
def get_settings() -> Settings:
    return Settings()
