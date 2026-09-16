from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.database import init_db
from app.core import pubsub

from app.workspace.authentication.controller.auth_controller import router as auth_router
from app.workspace.projects.controller.projects_controller import router as projects_router
from app.modeling.diagram.controller.boards_controller import router as boards_router
from app.modeling.ai.controller.chat_controller import router as chat_router
from app.modeling.ai.controller.guide_controller import router as guide_router
from app.generation.schema.controller.xmi_controller import router as xmi_router
from app.generation.code.controller.codegen_controller import router as codegen_router
from app.core.websocket.handlers import router as ws_router


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only in dev: create_all syncs the schema on startup.
    # In production use exclusively `alembic upgrade head`.
    if settings.dev_mode:
        await init_db()

    # Connect Redis Pub/Sub for cross-replica broadcast relay.
    # Degrades gracefully to single-replica mode if Redis is unreachable.
    try:
        await pubsub.init_redis()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Redis unavailable — single-replica mode active: %s", exc
        )

    yield

    await pubsub.close_redis()


app = FastAPI(
    title="dgram API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(boards_router, prefix="/api/boards", tags=["boards"])
app.include_router(projects_router, prefix="/api", tags=["projects"])
app.include_router(xmi_router, prefix="/api", tags=["xmi"])
app.include_router(codegen_router, prefix="/api/codegen", tags=["codegen"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(guide_router, prefix="/api/guide", tags=["guide"])
app.include_router(ws_router, tags=["websocket"])


@app.get("/health")
async def health():
    return {"status": "ok"}
