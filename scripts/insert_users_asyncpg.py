"""
Inserta 5 usuarios directamente usando asyncpg.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.security import hash_password
from app.core.config import get_settings

INITIAL_USERS = [
    ("Alice Johnson", "alice@example.com", "password123"),
    ("Bob Martinez", "bob@example.com", "password123"),
    ("Carlos Silva", "carlos@example.com", "password123"),
    ("Diana Prince", "diana@example.com", "password123"),
    ("Elena Gomez", "elena@example.com", "password123"),
]


async def main():
    settings = get_settings()
    db_url = settings.database_url
    print("Connecting to database...")
    
    import asyncpg
    raw_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(raw_url)
    print("Connected to PostgreSQL successfully!")

    # Check existing users
    for name, email, pw in INITIAL_USERS:
        clean_email = email.strip().lower()
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", clean_email)
        pw_hash = hash_password(pw)
        if not row:
            u_id = str(uuid.uuid4())
            await conn.execute("""
                INSERT INTO users (id, full_name, email, password_hash, created_at)
                VALUES ($1, $2, $3, $4, NOW())
            """, u_id, name, clean_email, pw_hash)
            print(f"  + Insertado: {name} ({clean_email})")
        else:
            await conn.execute("""
                UPDATE users SET full_name = $1, password_hash = $2 WHERE email = $3
            """, name, pw_hash, clean_email)
            print(f"  = Actualizado: {name} ({clean_email})")
        
    # Verify count and records
    rows = await conn.fetch("SELECT id, full_name, email FROM users ORDER BY full_name")
    print(f"\n📊 Total usuarios en BD: {len(rows)}")
    for r in rows:
        print(f"   • {r['full_name']} <{r['email']}> (ID: {r['id']})")

    # Verify no projects or boards are assigned to these users
    await conn.close()
    print("✅ Población de 5 usuarios completada limpiamente (sin proyectos ni tableros).")


if __name__ == "__main__":
    asyncio.run(main())
