"""
Script de migración directa de esquema usando asyncpg para PostgreSQL.
Añade columnas faltantes de forma segura e idempotente.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_settings


async def main():
    settings = get_settings()
    db_url = settings.database_url
    print("Conectando a PostgreSQL para sincronizar esquema...")

    import asyncpg
    raw_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(raw_url)
    print("Conexión establecida con éxito.")

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
            await conn.execute(sql)
            print(f"  ✓ {sql}")
        except Exception as exc:
            print(f"  ⚠ Error ejecutando '{sql}': {exc}")

    await conn.close()
    print("✅ Sincronización de esquema PostgreSQL completada.")


if __name__ == "__main__":
    asyncio.run(main())
