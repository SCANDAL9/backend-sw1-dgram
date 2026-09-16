"""
vertex_client.py — Cliente para Google Cloud Vertex AI (Gemini 2.0 Flash / 1.5 Flash).
Soporta autenticación con ADC (Application Default Credentials) o Service Account JSON.
Incluye soporte para Function Calling y Vision OCR multimodal para diagramas UML.
"""
import os
import json
import base64
import logging
from typing import Any
import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)

VERTEX_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "create_class",
                "description": "Crea una nueva clase, entidad o tabla en el diagrama UML",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {
                            "type": "STRING",
                            "description": "Nombre de la clase o entidad en CamelCase (ej. User, Order, Product)",
                        },
                        "attributes": {
                            "type": "ARRAY",
                            "description": "Lista de atributos de la clase",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "name": {"type": "STRING", "description": "Nombre del atributo"},
                                    "type": {
                                        "type": "STRING",
                                        "description": "Tipo de dato (VARCHAR, INTEGER, BOOLEAN, DECIMAL, TIMESTAMPTZ, etc.)",
                                    },
                                    "pk": {"type": "BOOLEAN", "description": "Si es clave primaria"},
                                    "fk": {"type": "BOOLEAN", "description": "Si es clave foránea"},
                                },
                                "required": ["name"],
                            },
                        },
                        "x": {"type": "NUMBER", "description": "Posición X en el lienzo"},
                        "y": {"type": "NUMBER", "description": "Posición Y en el lienzo"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "add_attribute",
                "description": "Añade un atributo a una clase existente",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "class_name": {"type": "STRING", "description": "Nombre de la clase"},
                        "attribute_name": {"type": "STRING", "description": "Nombre del atributo"},
                        "attribute_type": {"type": "STRING", "description": "Tipo de dato SQL/UML"},
                        "pk": {"type": "BOOLEAN", "description": "Si es clave primaria"},
                    },
                    "required": ["class_name", "attribute_name"],
                },
            },
            {
                "name": "create_association",
                "description": "Crea una relación o asociación entre dos clases",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "source_class": {"type": "STRING", "description": "Nombre de la clase origen"},
                        "target_class": {"type": "STRING", "description": "Nombre de la clase destino"},
                        "type": {
                            "type": "STRING",
                            "enum": ["1:1", "1:N", "N:M", "association", "aggregation", "composition", "generalization"],
                            "description": "Tipo de relación",
                        },
                        "name": {"type": "STRING", "description": "Nombre opcional de la relación"},
                    },
                    "required": ["source_class", "target_class"],
                },
            },
            {
                "name": "update_class",
                "description": "Modifica las propiedades de una clase existente (ej. renombrar clase o marcar abstracta)",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "class_name": {"type": "STRING", "description": "Nombre actual de la clase a modificar"},
                        "new_name": {"type": "STRING", "description": "Nuevo nombre para la clase (opcional)"},
                        "is_abstract": {"type": "BOOLEAN", "description": "Si la clase es abstracta (opcional)"},
                    },
                    "required": ["class_name"],
                },
            },
            {
                "name": "delete_class",
                "description": "Elimina una clase o entidad existente del diagrama UML",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "class_name": {"type": "STRING", "description": "Nombre de la clase a eliminar"},
                    },
                    "required": ["class_name"],
                },
            },
            {
                "name": "update_attribute",
                "description": "Modifica un atributo existente en una clase (cambia tipo de dato, nombre, PK, etc.)",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "class_name": {"type": "STRING", "description": "Nombre de la clase que contiene el atributo"},
                        "attribute_name": {"type": "STRING", "description": "Nombre actual del atributo a modificar"},
                        "new_type": {"type": "STRING", "description": "Nuevo tipo de dato SQL/UML (opcional)"},
                        "new_name": {"type": "STRING", "description": "Nuevo nombre para el atributo (opcional)"},
                        "pk": {"type": "BOOLEAN", "description": "Si es clave primaria (opcional)"},
                    },
                    "required": ["class_name", "attribute_name"],
                },
            },
            {
                "name": "delete_attribute",
                "description": "Elimina un atributo de una clase existente",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "class_name": {"type": "STRING", "description": "Nombre de la clase"},
                        "attribute_name": {"type": "STRING", "description": "Nombre del atributo a eliminar"},
                    },
                    "required": ["class_name", "attribute_name"],
                },
            },
            {
                "name": "delete_association",
                "description": "Elimina una relación o asociación existente entre dos clases",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "source_class": {"type": "STRING", "description": "Nombre de la clase origen"},
                        "target_class": {"type": "STRING", "description": "Nombre de la clase destino"},
                    },
                    "required": ["source_class", "target_class"],
                },
            },
        ]
    }
]


class VertexAIClient:
    def __init__(self):
        self.settings = get_settings()
        self._access_token: str | None = None
        self._project_id = self.settings.gcp_project_id
        self._location = self.settings.gcp_location
        self._model = self.settings.vertex_model_name

    def _get_auth_token_and_project(self) -> tuple[str | None, str | None]:
        """Obtiene el token OAuth2 y project_id usando google-auth (ADC o JSON)."""
        from pathlib import Path

        creds_candidate = (
            self.settings.google_application_credentials
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            or ".key/vertex.json"
        )

        # Candidates to resolve creds path
        resolved_path: Path | None = None
        base_dir = Path(__file__).resolve().parents[3]  # backend root (dgram/backend)

        possible_paths = [
            Path(creds_candidate),
            base_dir / creds_candidate,
            base_dir / ".key" / "vertex.json",
            Path.cwd() / creds_candidate,
            Path.cwd() / ".key" / "vertex.json",
            Path.cwd() / "backend" / ".key" / "vertex.json",
        ]

        for p in possible_paths:
            if p.exists() and p.is_file():
                resolved_path = p
                break

        try:
            import google.auth
            import google.auth.transport.requests

            if resolved_path:
                from google.oauth2 import service_account

                creds = service_account.Credentials.from_service_account_file(
                    str(resolved_path),
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                request = google.auth.transport.requests.Request()
                creds.refresh(request)
                project = getattr(creds, "project_id", None) or self._project_id
                self._project_id = project
                return creds.token, project
            else:
                creds, project = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                request = google.auth.transport.requests.Request()
                creds.refresh(request)
                proj = project or self._project_id
                self._project_id = proj
                return creds.token, proj
        except Exception as e:
            logger.info("No se pudieron cargar credenciales de GCP Vertex AI: %s", e)
            return None, self._project_id

    def _get_endpoint_url(self, project: str) -> str:
        host = "aiplatform.googleapis.com" if self._location.lower() == "global" else f"{self._location}-aiplatform.googleapis.com"
        return f"https://{host}/v1/projects/{project}/locations/{self._location}/publishers/google/models/{self._model}:generateContent"

    async def generate_chat_response(
        self,
        user_prompt: str,
        current_state: dict,
        system_instruction: str | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Envía el mensaje a Vertex AI Gemini con function calling.
        Retorna (texto_respuesta, lista_de_llamadas_a_funciones).
        """
        token, project = self._get_auth_token_and_project()
        if not token or not project:
            logger.info("Vertex AI no configurado. Usando fallback heurístico.")
            return self._heuristic_fallback(user_prompt, current_state)

        url = self._get_endpoint_url(project)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        context_str = json.dumps(current_state, ensure_ascii=False)
        sys_prompt = (
            system_instruction
            or (
                "Eres un arquitecto de software y asistente experto en diseño de diagramas UML y ER para dgram. "
                "Tu objetivo es ayudar al usuario a modelar sus clases, entidades y relaciones.\n"
                "REGLAS OBLIGATORIAS:\n"
                "1. NUNCA inventes o asumas una clase inexistente para satisfacer una asociación. Si la clase origen o destino referenciada no existe en el diagrama actual, DEBES indicarlo claramente en texto y preguntar al usuario si desea crearla primero, SIN invocar create_class ni create_association para esa entidad ficticia.\n"
                "2. Ante preguntas consultivas o consejos (ej. '¿debería agregar un campo X?', '¿conviene normalizar Y?'), responde en texto analizando ventajas y desventajas conceptuales. NUNCA ejecutes herramientas (add_attribute, create_class, etc.) para preguntas consultivas salvo que el usuario dé una orden imperativa explícita.\n"
                "3. Si se te pide modificar o agregar un atributo a una entidad ambigua (varias clases candidatas), NO invoques herramientas sobre todas ellas; pide al usuario que aclare a cuál entidad se refiere.\n"
                "4. Cuando el usuario te dé una orden directa de creación o adición válida, UTILIZA LAS HERRAMIENTAS (create_class, add_attribute, create_association).\n"
                f"Estado actual del diagrama:\n{context_str}"
            )
        )

        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "system_instruction": {
                "parts": [{"text": sys_prompt}]
            },
            "tools": VERTEX_TOOLS,
            "generation_config": {
                "temperature": 0.2,
                "max_output_tokens": 1024,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code != 200:
                    logger.error("Error en Vertex AI API (%d): %s", resp.status_code, resp.text)
                    return self._heuristic_fallback(user_prompt, current_state)

                data = resp.json()
                return self._parse_vertex_response(data, user_prompt, current_state)
        except Exception as e:
            logger.error("Excepción llamando a Vertex AI: %s", e)
            return self._heuristic_fallback(user_prompt, current_state)

    async def analyze_diagram_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        user_prompt: str | None = None,
        current_state: dict | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Vision OCR Multimodal: Analiza una imagen de pizarra o boceto en papel y extrae clases y relaciones.
        """
        token, project = self._get_auth_token_and_project()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        if not token or not project:
            logger.info("Vertex AI no configurado para Vision. Usando fallback de OCR de prueba.")
            return (
                "Se procesó la imagen del boceto (modo local/demo). Se detectaron entidades sugeridas.",
                [
                    {
                        "name": "create_class",
                        "args": {
                            "name": "Usuario",
                            "attributes": [
                                {"name": "id", "type": "INTEGER", "pk": True},
                                {"name": "email", "type": "VARCHAR(255)"},
                                {"name": "nombre", "type": "VARCHAR(255)"},
                            ],
                            "x": 250,
                            "y": 180,
                        },
                    },
                    {
                        "name": "create_class",
                        "args": {
                            "name": "Pedido",
                            "attributes": [
                                {"name": "id", "type": "INTEGER", "pk": True},
                                {"name": "total", "type": "DECIMAL(10,2)"},
                                {"name": "estado", "type": "VARCHAR(50)"},
                            ],
                            "x": 550,
                            "y": 180,
                        },
                    },
                    {
                        "name": "create_association",
                        "args": {
                            "source_class": "Usuario",
                            "target_class": "Pedido",
                            "type": "1:N",
                            "name": "realiza",
                        },
                    },
                ],
            )

        url = self._get_endpoint_url(project)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        prompt_text = (
            user_prompt
            or "Analiza esta imagen que contiene un diagrama UML o ER dibujado a mano/pizarra. "
            "Extrae con precisión todas las entidades/clases, sus atributos con sus tipos de datos (y si son PK/FK), "
            "y las relaciones o asociaciones entre ellas. Usa las herramientas de función para crearlas todas."
        )

        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_image,
                            }
                        },
                        {"text": prompt_text},
                    ],
                }
            ],
            "tools": VERTEX_TOOLS,
            "generation_config": {
                "temperature": 0.1,
                "max_output_tokens": 2048,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code != 200:
                    logger.error("Error en Vertex AI Vision (%d): %s", resp.status_code, resp.text)
                    return "No se pudo procesar la imagen con Vertex AI.", []
                data = resp.json()
                return self._parse_vertex_response(data, prompt_text, current_state or {})
        except Exception as e:
            logger.error("Error llamando a Vertex AI Vision: %s", e)
            return f"Error al procesar la imagen: {str(e)}", []

    def _parse_vertex_response(
        self, data: dict, user_prompt: str, current_state: dict
    ) -> tuple[str, list[dict]]:
        """Extrae el texto de respuesta y las llamadas a herramientas de la respuesta de Vertex AI."""
        candidates = data.get("candidates", [])
        if not candidates:
            return "No se obtuvo respuesta del modelo.", []

        first_cand = candidates[0]
        content = first_cand.get("content", {})
        parts = content.get("parts", [])

        reply_texts = []
        function_calls = []

        for p in parts:
            if "text" in p:
                reply_texts.append(p["text"])
            if "functionCall" in p:
                fc = p["functionCall"]
                function_calls.append({
                    "name": fc.get("name"),
                    "args": fc.get("args", {}),
                })

        reply_msg = "\n".join(reply_texts) if reply_texts else "He aplicado los cambios al diagrama."
        return reply_msg, function_calls

    def _heuristic_fallback(self, user_prompt: str, current_state: dict) -> tuple[str, list[dict]]:
        """Fallback heurístico determinista para desarrollo offline o sin credenciales GCP."""
        import re

        prompt_lower = user_prompt.lower()
        tool_calls: list[dict] = []

        create_match = re.search(
            r"(?:crea|agrega|añade|nueva)\s+(?:una\s+|un\s+)?(?:tabla|clase|entidad)\s+([a-zA-Z0-9_]+)",
            prompt_lower,
        )
        if create_match:
            class_name = create_match.group(1).capitalize()
            attrs = [{"name": "id", "type": "INTEGER", "pk": True, "fk": False}]
            if "email" in prompt_lower:
                attrs.append({"name": "email", "type": "VARCHAR(255)", "pk": False, "fk": False})
            if "nombre" in prompt_lower or "name" in prompt_lower:
                attrs.append({"name": "nombre", "type": "VARCHAR(255)", "pk": False, "fk": False})
            if "precio" in prompt_lower or "price" in prompt_lower:
                attrs.append({"name": "precio", "type": "DECIMAL(10,2)", "pk": False, "fk": False})
            if "fecha" in prompt_lower or "date" in prompt_lower:
                attrs.append({"name": "fecha_creacion", "type": "TIMESTAMPTZ", "pk": False, "fk": False})

            tool_calls.append({
                "name": "create_class",
                "args": {
                    "name": class_name,
                    "attributes": attrs,
                    "x": 200 + (len(current_state.get("entities", [])) * 60),
                    "y": 150,
                },
            })
            reply = f"He creado la clase **{class_name}** con sus atributos correspondientes en el diagrama."
        else:
            reply = (
                f"He recibido tu instrucción: '{user_prompt}'. "
                "Puedes pedirme crear clases (ej. 'crea una clase Producto con nombre y precio') o subir una foto de un diagrama en pizarra."
            )

        return reply, tool_calls

    async def generate_guide_response(
        self,
        target_context: dict[str, Any],
        question: str | None = None,
        diagram_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Genera explicación de mentoría o respuesta contextual para el agente de guía/onboarding.
        No usa function calling ni altera el diagrama.
        """
        token, project = self._get_auth_token_and_project()

        target_type = target_context.get("target_type", "unknown")
        target_meta = target_context.get("target_meta", {})
        entity_name = target_meta.get("name") or target_meta.get("entity_name") or ""
        attrs = target_meta.get("attributes") or []

        system_instruction = (
            "Eres el Spatial AI Guide de dgram — un arquitecto de software senior y mentor paciente "
            "embebido directamente en el lienzo de diagramación UML/ER. Tu misión es enseñar, guiar y explicar "
            "conceptos de diseño de software, modelado de bases de datos y la arquitectura del sistema. "
            "REGLAS:\n"
            "1. NUNCA generes comandos de mutación de diagrama. Tu rol es 100% de mentoría y explicación.\n"
            "2. Sé conciso y directo (máximo 120 palabras en la explicación).\n"
            "3. Explica el elemento específico en el contexto del diagrama actual, no solo definiciones de diccionario.\n"
            "4. Responde SIEMPRE en formato JSON válido con las claves exactas:\n"
            '   {"title": "...", "explanation": "...", "tip": "...", "next_step": {"label": "...", "action_hint": "..."}, "followups": ["...", "..."]}'
        )

        user_prompt_parts = [
            f"Elemento inspeccionado: tipo='{target_type}', detalles={json.dumps(target_meta, ensure_ascii=False)}.",
        ]
        if diagram_state:
            entities_count = len(diagram_state.get("entities", []))
            relations_count = len(diagram_state.get("relations", []))
            user_prompt_parts.append(
                f"Contexto del diagrama: {entities_count} entidades, {relations_count} relaciones."
            )
        if question:
            user_prompt_parts.append(f"Pregunta del usuario: '{question}'.")
        else:
            user_prompt_parts.append("Explica qué es este elemento, para qué sirve y qué buenas prácticas aplican.")

        prompt_str = "\n".join(user_prompt_parts)

        if not token or not project:
            # Fallback determinista local de mentoría
            return self._heuristic_guide_fallback(target_type, target_meta, question, diagram_state)

        url = self._get_endpoint_url(project)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_str}],
                }
            ],
            "system_instruction": {
                "parts": [{"text": system_instruction}],
            },
            "generation_config": {
                "temperature": 0.5,
                "max_output_tokens": 1024,
                "response_mime_type": "application/json",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, json=body)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        try:
                            parsed = json.loads(raw_text)
                            if isinstance(parsed, dict) and "explanation" in parsed:
                                return parsed
                        except Exception:
                            pass
                logger.warning("Vertex AI Guide response no fue JSON válido o falló HTTP: %s", res.status_code)
        except Exception as e:
            logger.info("Fallo en llamada a Vertex AI Guide (%s). Usando fallback.", e)

        return self._heuristic_guide_fallback(target_type, target_meta, question, diagram_state)

    def _heuristic_guide_fallback(
        self,
        target_type: str,
        target_meta: dict[str, Any],
        question: str | None = None,
        diagram_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Respuesta heurística de guía cuando Vertex AI no está disponible."""
        name = target_meta.get("name") or target_meta.get("entity_name") or "Elemento"
        if target_type in ("entity", "entity:node"):
            attrs = target_meta.get("attributes") or []
            attr_count = len(attrs)
            return {
                "title": f"Clase / Entidad: {name}",
                "explanation": (
                    f"Representa el concepto central de **{name}** en tu dominio. "
                    f"Actualmente cuenta con {attr_count} atributo(s). En UML y modelado relacional, "
                    "esta clase define la estructura de datos y las responsabilidades del objeto."
                ),
                "tip": "Mantén alta cohesión: cada clase debe tener una única responsabilidad (principio SRP).",
                "next_step": {
                    "label": "Definir relaciones",
                    "action_hint": "Arrastra desde el conector hacia otra clase para asociarlas.",
                },
                "followups": [
                    f"¿Qué relaciones debería tener {name}?",
                    "¿Cómo normalizo los atributos de esta tabla?",
                    "¿Debe ser una clase abstracta?",
                ],
            }
        elif target_type in ("relation", "relation:edge"):
            return {
                "title": f"Relación UML: {target_meta.get('type', 'Asociación')}",
                "explanation": (
                    "Define la cardinalidad y dependencia estructural entre dos entidades. "
                    "Determina cómo se propagan las claves foráneas en bases de datos relacionales."
                ),
                "tip": "Revisa siempre las multiplicidades en ambos extremos (ej. 1 a muchos vs muchos a muchos).",
                "next_step": {
                    "label": "Verificar cardinalidad",
                    "action_hint": "Selecciona la relación para editar el tipo o multiplicidad.",
                },
                "followups": [
                    "¿Cuándo conviene usar composición en lugar de asociación?",
                    "¿Cómo resuelvo una relación N:M?",
                ],
            }
        elif target_type in ("attribute", "attribute:row"):
            attr_name = target_meta.get("attribute_name", "campo")
            attr_type = target_meta.get("attribute_type", "VARCHAR")
            return {
                "title": f"Atributo: {attr_name} ({attr_type})",
                "explanation": (
                    f"Propiedad tipada perteneciente a la entidad. El tipo `{attr_type}` restringe "
                    "los valores admisibles y optimiza el almacenamiento en base de datos."
                ),
                "tip": "Si este atributo es identificador único, asegúrate de marcarlo como Clave Primaria (PK).",
                "next_step": {
                    "label": "Configurar restricciones",
                    "action_hint": "Haz doble clic para cambiar si es PK, FK o nullable.",
                },
                "followups": [
                    "¿Qué tipo de dato es más eficiente para identificadores?",
                    "¿Cuándo un campo debe permitir nulos?",
                ],
            }
        else:
            return {
                "title": "Guía Interactiva dgram",
                "explanation": (
                    "Estás utilizando el lienzo colaborativo de dgram. Puedes arrastrar esta burbuja "
                    "sobre cualquier botón, clase o relación para recibir explicaciones arquitecturales instantáneas."
                ),
                "tip": "Usa Ctrl+K para abrir la paleta de comandos rápidos.",
                "next_step": {
                    "label": "Crear primera clase",
                    "action_hint": "Presiona el botón + en la barra superior.",
                },
                "followups": [
                    "¿Cómo exporto mi diagrama a SQL o código?",
                    "¿Cómo funciona la colaboración en tiempo real?",
                ],
            }


vertex_ai_client = VertexAIClient()
