"""
Script para sembrar 5 usuarios iniciales sin proyectos ni datos adicionales.
Ejecución: python -m scripts.seed_users o python scripts/seed_users.py
"""
import asyncio
import os
import sys

# Agregar path raíz del backend
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.core.database import async_session_factory
from app.workspace.authentication.entity.user_entity import User
from app.core.security import hash_password

INITIAL_USERS = [
    {
        "full_name": "Alice Johnson",
        "email": "alice@example.com",
        "password": "password123",
        "avatar_url": None,
    },
    {
        "full_name": "Bob Martinez",
        "email": "bob@example.com",
        "password": "password123",
        "avatar_url": None,
    },
    {
        "full_name": "Carlos Silva",
        "email": "carlos@example.com",
        "password": "password123",
        "avatar_url": None,
    },
    {
        "full_name": "Diana Prince",
        "email": "diana@example.com",
        "password": "password123",
        "avatar_url": None,
    },
    {
        "full_name": "Elena Gomez",
        "email": "elena@example.com",
        "password": "password123",
        "avatar_url": None,
    },
]


async def seed_users():
    print("🌱 Sembrando población inicial de 5 usuarios...")
    async with async_session_factory() as session:
        created_count = 0
        for u_data in INITIAL_USERS:
            clean_email = u_data["email"].strip().lower()
            res = await session.execute(select(User).where(User.email == clean_email))
            existing = res.scalar_one_or_none()
            if not existing:
                user = User(
                    full_name=u_data["full_name"],
                    email=clean_email,
                    password_hash=hash_password(u_data["password"]),
                    avatar_url=u_data["avatar_url"],
                )
                session.add(user)
                created_count += 1
                print(f"  + Creado: {u_data['full_name']} ({clean_email})")
            else:
                print(f"  = Ya existía: {u_data['full_name']} ({clean_email})")

        await session.commit()
        print(f"✅ Finalizado: {created_count} usuarios nuevos sembrados.")


if __name__ == "__main__":
    asyncio.run(seed_users())
