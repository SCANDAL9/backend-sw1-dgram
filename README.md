# dgram — Backend API

Backend asíncrono de alto rendimiento para **dgram**, una plataforma colaborativa en tiempo real de modelado de diagramas UML y entidad-relación con asistencia de IA multimodal (Google Cloud Vertex AI / Gemini).

---

## Stack Tecnológico

- **Framework**: FastAPI (Python 3.12+)
- **Base de Datos**: PostgreSQL 16 con SQLAlchemy 2.0 (AsyncIO + `asyncpg`)
- **Migraciones**: Alembic
- **Caché y Mensajería**: Redis 7 (Pub/Sub cross-replica relay)
- **CRDT / Colaboración**: Yjs (`pycrdt`)
- **Inteligencia Artificial**: Google Cloud Vertex AI (Gemini 2.0 Flash) & Vision OCR
- **Testing**: Pytest + Pytest-AsyncIO (89 pruebas automatizadas)

---

## Estructura del Repositorio

```
backend/
├── alembic/              # Versiones y scripts de migración de esquema
│   └── versions/         # 17 migraciones deterministas
├── alembic.ini           # Configuración de Alembic
├── app/
│   ├── api/              # Routers HTTP (auth, boards, projects, codegen, chat, etc.)
│   ├── models/           # Modelos relacionales SQLAlchemy
│   ├── schemas/          # Esquemas de validación Pydantic v2
│   ├── services/         # Lógica de dominio, orquestación IA y comandos
│   └── websocket/        # Handlers y ConnectionManager en tiempo real
├── tests/                # Suite de pruebas unitarias, resiliencia y seguridad
├── Dockerfile            # Construcción de imagen de producción
├── entrypoint.sh         # Script de entrada (ejecuta migraciones antes de Uvicorn)
├── requirements.txt      # Dependencias del proyecto
└── run.sh                # Script de inicio local en entorno Nix
```

---

## Configuración y Variables de Entorno

Copia la plantilla de variables de entorno y ajusta los valores necesarios:

```bash
cp .env.example .env
```

Variables clave en `.env`:
- `DATABASE_URL`: Conexión asíncrona a PostgreSQL (`postgresql+asyncpg://...`)
- `REDIS_URL`: Conexión a Redis (`redis://...`)
- `JWT_SECRET_KEY`: Clave secreta para firma de tokens JWT
- `DEV_MODE`: `true` en desarrollo local, `false` en producción
- `WEB_CONCURRENCY`: Número de workers Uvicorn en producción (por defecto `2`)
- `GCP_PROJECT_ID`: ID del proyecto en Google Cloud para Vertex AI
- `GOOGLE_APPLICATION_CREDENTIALS`: Ruta al archivo JSON de cuenta de servicio

---

## Instalación y Ejecución Local

### 1. Crear y activar entorno virtual
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Ejecutar migraciones de base de datos
```bash
alembic upgrade head
```

### 3. Iniciar el servidor de desarrollo
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

O utilizando el script preconfigurado:
```bash
./run.sh
```

La documentación interactiva de la API estará disponible en `http://localhost:8000/docs`.

---

## Ejecución de Pruebas

La suite consta de 89 pruebas que cubren lógica de dominio, concurrencia, seguridad y resiliencia de IA:

```bash
pytest tests -W error::RuntimeWarning
```
