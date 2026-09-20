from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings


settings = get_settings()

engine = create_async_engine(settings.database_url, echo=True)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


from sqlalchemy import text


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Sincronización idempotente de columnas para PostgreSQL
        schema_updates = [
            "ALTER TABLE class_element ADD COLUMN IF NOT EXISTS external_ref VARCHAR(255);",
            "ALTER TABLE class_element ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual';",
            "ALTER TABLE class_element ADD COLUMN IF NOT EXISTS created_by VARCHAR(36);",
            "ALTER TABLE class_element ADD COLUMN IF NOT EXISTS is_abstract BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE attribute ADD COLUMN IF NOT EXISTS is_pkey BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE attribute ADD COLUMN IF NOT EXISTS is_fkey BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE attribute ADD COLUMN IF NOT EXISTS is_derived BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE attribute ADD COLUMN IF NOT EXISTS default_value VARCHAR(255);",
            "ALTER TABLE attribute ADD COLUMN IF NOT EXISTS order_index INTEGER DEFAULT 0;",
            "ALTER TABLE association ADD COLUMN IF NOT EXISTS source_role VARCHAR(100);",
            "ALTER TABLE association ADD COLUMN IF NOT EXISTS target_role VARCHAR(100);",
            "ALTER TABLE association ADD COLUMN IF NOT EXISTS source_multiplicity VARCHAR(20);",
            "ALTER TABLE association ADD COLUMN IF NOT EXISTS target_multiplicity VARCHAR(20);",
            "ALTER TABLE boards ADD COLUMN IF NOT EXISTS yjs_state BYTEA;",
        ]
        for sql in schema_updates:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass
