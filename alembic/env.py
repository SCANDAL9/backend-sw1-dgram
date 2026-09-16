from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import asyncio

# Importar Base primero
from app.models.database import Base

# --- Importar todos los modelos para que target_metadata los registre ---
from app.models.user import User            # noqa: F401
from app.models.board import Board          # noqa: F401
from app.models.project import (            # noqa: F401
    Project, ProjectMember,
)
from app.models.uml import (                # noqa: F401
    Package, ClassElement, Attribute,
    Association, AssociationClassLink,
)
from app.models.board_normalized import (   # noqa: F401
    BoardHistory, BoardSnapshot, BoardElement,
)
from app.models.chat import (               # noqa: F401
    ChatConversation, ChatMessage, ChatAttachment, AiAction,
)

# --- Configuración de logging ---
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inyectar DATABASE_URL desde get_settings() para no depender del valor
# hardcodeado en alembic.ini (que usaba postgres:postgres vs postgres:password)
from app.config import get_settings
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
