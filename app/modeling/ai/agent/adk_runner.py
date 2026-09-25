"""
adk_runner.py — Google Cloud ADK / Agent Platform Runner para dgram.
Gestiona el ciclo nativo de Function Calling con Gemini 3.6 Flash en Vertex AI.
Registra el Agent Execution Trace estructurado (Agente, Tool, Input, Output, Status)
sin exponer ni persistir Chain-of-Thought interno.
"""
import time
import json
import logging
from typing import Any
import httpx
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modeling.ai.agent.vertex_client import vertex_ai_client
from app.modeling.ai.agent.agent_session import AgentSessionState
from app.modeling.ai.agent.agent_tools import (
    tool_get_class_details,
    tool_get_diagram_summary,
    tool_execute_diagram_command,
    tool_emit_ui_action,
    tool_get_project_memory,
    ClassDetail,
    DiagramSummary,
    CommandExecutionResult,
)
from app.modeling.diagram.dto.command_dto import CommandType

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MODELO DE TRAZABILIDAD (AGENT EXECUTION TRACE)
# ─────────────────────────────────────────────────────────────────────────────

class AgentExecutionTrace(BaseModel):
    agent_name: str
    action_name: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None = None
    status: str = "success"  # "success" | "failed"
    error_message: str | None = None
    latency_ms: float | None = None
    timestamp: float = Field(default_factory=time.time)


class AgentRunResult(BaseModel):
    agent_name: str
    reply_text: str
    traces: list[AgentExecutionTrace] = Field(default_factory=list)
    commands_executed: list[CommandExecutionResult] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# DECLARACIÓN FORMAL DE TOOLS PARA VERTEX AI / GEMINI
# ─────────────────────────────────────────────────────────────────────────────

ADK_TOOLS_DECLARATIONS = [
    {
        "function_declarations": [
            {
                "name": "get_project_memory",
                "description": "Obtiene las directivas de arquitectura, convenciones de diseño y reglas de negocio persistentes del Memory Bank del proyecto.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {},
                },
            },
            {
                "name": "get_class_details",
                "description": "Obtiene los detalles reales (atributos, tipos, PK, FK y asociaciones) de una clase existente en el diagrama desde la base de datos.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "class_name": {
                            "type": "STRING",
                            "description": "Nombre exacto o aproximado de la clase en el diagrama.",
                        }
                    },
                    "required": ["class_name"],
                },
            },
            {
                "name": "get_diagram_summary",
                "description": "Obtiene un resumen cuantitativo del diagrama (total de clases, atributos, relaciones y lista de nombres).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {},
                },
            },

            {
                "name": "execute_diagram_command",
                "description": "Aplica una mutación al diagrama mediante el Command Protocol (crear clase, agregar atributo, crear relación, etc.).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "command_type": {
                            "type": "STRING",
                            "description": "Tipo de comando (CREATE_CLASS, ADD_ATTRIBUTE, CREATE_ASSOCIATION, UPDATE_CLASS, DELETE_CLASS, etc.)",
                        },
                        "payload": {
                            "type": "OBJECT",
                            "description": "Cuerpo del comando con propiedades requeridas (nombre, atributos, clase origen, destino, etc.)",
                        },
                    },
                    "required": ["command_type", "payload"],
                },
            },
            {
                "name": "create_package",
                "description": "Crea un paquete contenedor UML en el proyecto.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {
                            "type": "STRING",
                            "description": "Nombre del paquete (ej. Domain, Auth, Billing)",
                        }
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "assign_package",
                "description": "Asigna una entidad o clase a un paquete contenedor.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "entity_id": {"type": "STRING", "description": "ID de la clase"},
                        "package_id": {"type": "STRING", "description": "ID del paquete destino"},
                    },
                    "required": ["entity_id", "package_id"],
                },
            },
            {
                "name": "resize_entity",
                "description": "Ajusta el ancho y alto dimensional de una entidad en el lienzo.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "entity_id": {"type": "STRING", "description": "ID de la clase"},
                        "width": {"type": "NUMBER", "description": "Nuevo ancho (min 150)"},
                        "height": {"type": "NUMBER", "description": "Nuevo alto (min 100)"},
                    },
                    "required": ["entity_id", "width", "height"],
                },
            },
            {
                "name": "emit_ui_action",
                "description": "Emite una acción visual a la interfaz de usuario del cliente web (resaltar nodo, enfocar elemento o abrir panel).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action_type": {
                            "type": "STRING",
                            "enum": ["highlight", "focus", "pan", "open_panel"],
                            "description": "Tipo de acción visual en el cliente.",
                        },
                        "target_id": {
                            "type": "STRING",
                            "description": "ID o nombre del elemento visual objetivo (opcional).",
                        },
                        "pulse_color": {
                            "type": "STRING",
                            "description": "Color del pulso (indigo, emerald, amber, rose).",
                        },
                        "message": {
                            "type": "STRING",
                            "description": "Mensaje explicativo breve para mostrar junto al elemento (opcional).",
                        },
                    },
                    "required": ["action_type"],
                },
            },
        ]
    }
]


class ADKAgentRunner:
    """
    Ejecutor de agentes para Google Cloud Vertex AI (Gemini 3.6 Flash / Google ADK).
    Implementa el ciclo de tool calling nativo registrando cada paso en un AgentExecutionTrace.
    """

    def __init__(self, agent_name: str = "DiagramAgent"):
        self.agent_name = agent_name
        self.settings = get_settings()

    async def execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        db: AsyncSession,
        board_id: str,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], AgentExecutionTrace, CommandExecutionResult | None]:
        """
        Ejecuta una herramienta estructurada localmente y genera su traza de ejecución.
        """
        trace = AgentExecutionTrace(
            agent_name=self.agent_name,
            action_name=tool_name,
            input_payload=tool_args,
        )
        cmd_result: CommandExecutionResult | None = None
        output_dict: dict[str, Any] = {}

        try:
            if tool_name == "get_class_details":
                class_name = tool_args.get("class_name", "")
                detail = await tool_get_class_details(db, board_id, class_name)
                output_dict = detail.model_dump() if detail else {"found": False, "class_name": class_name}

            elif tool_name == "get_diagram_summary":
                summary = await tool_get_diagram_summary(db, board_id)
                output_dict = summary.model_dump()

            elif tool_name == "execute_diagram_command":
                cmd_type = tool_args.get("command_type", "")
                payload = tool_args.get("payload", {})
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=cmd_type,
                    payload=payload,
                )
                cmd_result = res
                output_dict = res.model_dump()

            elif tool_name == "get_project_memory":
                items = await tool_get_project_memory(db, board_id)
                output_dict = {"memories": [i.model_dump() for i in items]}

            elif tool_name == "emit_ui_action":
                action_type = tool_args.get("action_type", "highlight")
                target_id = tool_args.get("target_id")
                pulse_color = tool_args.get("pulse_color", "indigo")
                tab = tool_args.get("tab")
                message = tool_args.get("message")
                action_res = await tool_emit_ui_action(
                    board_id=board_id,
                    action_type=action_type,
                    target_id=target_id,
                    pulse_color=pulse_color,
                    tab=tab,
                    message=message,
                )
                output_dict = action_res.model_dump()


            elif tool_name == "create_package":
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=CommandType.CREATE_PACKAGE,
                    payload={"name": tool_args.get("name", "NuevoPaquete")},
                )
                cmd_result = res
                output_dict = res.model_dump()

            elif tool_name == "assign_package":
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=CommandType.ASSIGN_CLASS_PACKAGE,
                    payload={
                        "entity_id": tool_args.get("entity_id"),
                        "package_id": tool_args.get("package_id"),
                    },
                )
                cmd_result = res
                output_dict = res.model_dump()

            elif tool_name == "resize_entity":
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=CommandType.RESIZE_ENTITY,
                    payload={
                        "entity_id": tool_args.get("entity_id"),
                        "width": tool_args.get("width", 200),
                        "height": tool_args.get("height", 160),
                    },
                )
                cmd_result = res
                output_dict = res.model_dump()

            # Compatibilidad directa si Gemini invoca nombres canónicos anteriores:
            elif tool_name == "create_class":
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=CommandType.CREATE_ENTITY,
                    payload=tool_args,
                )
                cmd_result = res
                output_dict = res.model_dump()

            elif tool_name == "add_attribute":
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=CommandType.ADD_COLUMN,
                    payload=tool_args,
                )
                cmd_result = res
                output_dict = res.model_dump()

            elif tool_name == "create_association":
                res = await tool_execute_diagram_command(
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                    command_type=CommandType.CREATE_RELATION,
                    payload=tool_args,
                )
                cmd_result = res
                output_dict = res.model_dump()

            else:
                trace.status = "failed"
                trace.error_message = f"Herramienta desconocida: {tool_name}"
                output_dict = {"error": trace.error_message}

            trace.output_payload = output_dict
            if "error" in output_dict and trace.status == "success":
                trace.status = "failed"
                trace.error_message = str(output_dict["error"])

        except Exception as exc:
            logger.exception("Error ejecutando tool %s", tool_name)
            trace.status = "failed"
            trace.error_message = str(exc)
            output_dict = {"error": str(exc)}
            trace.output_payload = output_dict

        return output_dict, trace, cmd_result

    async def run(
        self,
        db: AsyncSession,
        board_id: str,
        user_prompt: str,
        user_id: str | None = None,
        system_instruction: str | None = None,
        session_state: AgentSessionState | None = None,
        max_turns: int = 5,
    ) -> AgentRunResult:
        """
        Ejecuta el ciclo de agente con Vertex AI Gemini y resolución nativa de Tools.
        """
        traces: list[AgentExecutionTrace] = []
        commands_executed: list[CommandExecutionResult] = []

        token, project = vertex_ai_client._get_auth_token_and_project()
        if not token or not project:
            logger.info("Vertex AI no autenticado. Usando fallback offline para %s.", self.agent_name)
            return await self._run_offline_fallback(
                db=db,
                board_id=board_id,
                user_prompt=user_prompt,
                user_id=user_id,
                session_state=session_state,
            )

        url = vertex_ai_client._get_endpoint_url(project)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        session_ctx = ""
        if session_state:
            session_ctx = (
                f"\n[Contexto del Usuario en Tiempo Real]\n"
                f"- Elemento actualmente seleccionado: {session_state.selected_element_id or 'Ninguno'}\n"
                f"- Herramienta activa en toolbar: {session_state.active_tool}\n"
                f"- Viewport: zoom={session_state.viewport.get('zoom', 1.0)}, pan=({session_state.viewport.get('pan_x', 0)}, {session_state.viewport.get('pan_y', 0)})\n"
            )

        from app.modeling.ai.service.project_memory_service import get_memories_for_board
        memories = await get_memories_for_board(db, board_id)
        memory_ctx = ""
        if memories:
            memory_lines = "\n".join(f"- [{m.category.upper()}] {m.directive}" for m in memories)
            memory_ctx = f"\n[Persistent Memory Bank - Directivas de Arquitectura del Proyecto]\n{memory_lines}\n"

        sys_prompt = (
            system_instruction
            or (
                f"Eres el {self.agent_name} de dgram, un sistema de arquitectura de software y modelado UML.\n"
                f"Tienes acceso a herramientas para consultar el estado real del diagrama y aplicar mutaciones mediante el Command Protocol.\n"
                f"NUNCA inventes IDs o clases si no las has verificado con las herramientas.\n"
                f"Mantén tus respuestas directas, profesionales y técnicas.\n"
                f"{session_ctx}"
                f"{memory_ctx}"
            )
        )


        contents: list[dict[str, Any]] = [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ]

        async with httpx.AsyncClient(timeout=45.0) as client:
            for turn in range(max_turns):
                body: dict[str, Any] = {
                    "contents": contents,
                    "system_instruction": {"parts": [{"text": sys_prompt}]},
                    "tools": ADK_TOOLS_DECLARATIONS,
                    "generation_config": {
                        "temperature": 0.2,
                        "max_output_tokens": 1024,
                    },
                }

                try:
                    resp = await client.post(url, headers=headers, json=body)
                    if resp.status_code != 200:
                        logger.error("Error en llamada a Vertex AI (%d): %s", resp.status_code, resp.text)
                        return await self._run_offline_fallback(
                            db=db,
                            board_id=board_id,
                            user_prompt=user_prompt,
                            user_id=user_id,
                            session_state=session_state,
                        )

                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        break

                    cand_content = candidates[0].get("content", {})
                    parts = cand_content.get("parts", [])

                    # Detectar si hay llamadas a funciones
                    function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
                    reply_texts = [p["text"] for p in parts if "text" in p]

                    if not function_calls:
                        final_text = "\n".join(reply_texts) if reply_texts else "Acción completada."
                        return AgentRunResult(
                            agent_name=self.agent_name,
                            reply_text=final_text,
                            traces=traces,
                            commands_executed=commands_executed,
                        )

                    # Añadir la respuesta del modelo al historial de contents
                    contents.append(cand_content)

                    # Ejecutar cada function call y preparar functionResponse
                    response_parts = []
                    for fc in function_calls:
                        f_name = fc.get("name", "")
                        f_args = fc.get("args", {})
                        out_dict, trace, cmd_res = await self.execute_tool(
                            tool_name=f_name,
                            tool_args=f_args,
                            db=db,
                            board_id=board_id,
                            user_id=user_id,
                        )
                        traces.append(trace)
                        if cmd_res:
                            commands_executed.append(cmd_res)

                        response_parts.append({
                            "functionResponse": {
                                "name": f_name,
                                "response": {
                                    "name": f_name,
                                    "content": out_dict,
                                }
                            }
                        })

                    contents.append({
                        "role": "user",
                        "parts": response_parts,
                    })

                except Exception as e:
                    logger.error("Error en turno %d de ADKAgentRunner: %s", turn, e)
                    return await self._run_offline_fallback(
                        db=db,
                        board_id=board_id,
                        user_prompt=user_prompt,
                        user_id=user_id,
                        session_state=session_state,
                    )

        return AgentRunResult(
            agent_name=self.agent_name,
            reply_text="Operación procesada.",
            traces=traces,
            commands_executed=commands_executed,
        )

    async def _run_offline_fallback(
        self,
        db: AsyncSession,
        board_id: str,
        user_prompt: str,
        user_id: str | None = None,
        session_state: AgentSessionState | None = None,
    ) -> AgentRunResult:
        """
        Fallback determinista para ejecución offline sin credenciales o en tests.
        Ejecuta las tools correspondientes detectadas por intención y produce trazas válidas.
        """
        import re
        traces: list[AgentExecutionTrace] = []
        commands_executed: list[CommandExecutionResult] = []

        prompt_lower = user_prompt.lower()

        # 0. Guide Agent fallback
        if self.agent_name == "GuideAgent":
            guide_reply = (
                "¡Hola! Soy tu **GuideAgent** (mentor de dgram).\n\n"
                "• **Crear clases**: Haz clic en el botón '+' en la barra superior o indícamelo aquí (ej. *'Crea una clase Pedido con total y fecha'*).\n"
                "• **Relaciones**: Arrastra desde el conector de una clase hacia la clase destino en el lienzo.\n"
                "• **Visibilidad**: Oculta o muestra entidades desde el panel explorador con el icono del ojo.\n"
                "• **Atajos**: `Ctrl+Z` (deshacer), `Ctrl+Y` (rehacer), `Delete` (eliminar seleccionado).\n"
                "• **Exportar**: Usa el botón de exportación en la cabecera para obtener código Spring Boot 3 o diagrama en imagen."
            )
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=guide_reply,
                traces=traces,
                commands_executed=commands_executed,
            )

        # 0.1 CodeGen Agent fallback
        if self.agent_name == "CodeGenAgent":
            out, tr, _ = await self.execute_tool(
                tool_name="get_diagram_summary",
                tool_args={},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            summary = DiagramSummary(**out)
            sample_class = summary.class_names[0] if summary.class_names else "Entity"
            codegen_reply = (
                f"Aquí tienes el modelo de entidad Spring Boot 3.3.x (Java 21) para `{sample_class}`:\n\n"
                f"```java\n"
                f"package com.dgram.generated.entity;\n\n"
                f"import jakarta.persistence.*;\n"
                f"import lombok.*;\n\n"
                f"@Entity\n"
                f"@Table(name = \"{sample_class.lower()}\")\n"
                f"@Getter @Setter\n"
                f"@NoArgsConstructor @AllArgsConstructor\n"
                f"@Builder\n"
                f"public class {sample_class} {{\n"
                f"    @Id\n"
                f"    @GeneratedValue(strategy = GenerationType.IDENTITY)\n"
                f"    private Long id;\n"
                f"}}\n"
                f"```\n\n"
                f"*(Puedes pedirme generar Repositories, DTOs Records y RestControllers para cualquier entidad del diagrama)*"
            )
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=codegen_reply,
                traces=traces,
                commands_executed=commands_executed,
            )

        # 1. Consulta / Resumen
        if any(w in prompt_lower for w in ["resumen", "summary", "cuantas clases", "métricas", "metricas"]):
            out, tr, _ = await self.execute_tool(
                tool_name="get_diagram_summary",
                tool_args={},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            summary = DiagramSummary(**out)
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=f"El diagrama contiene {summary.total_classes} clases y {summary.total_associations} asociaciones: {', '.join(summary.class_names)}.",
                traces=traces,
                commands_executed=commands_executed,
            )

        # 2. Detalle de clase
        details_match = re.search(r"(?:detalle|atributos|campos|estructura)\s+(?:de\s+)?([a-zA-Z0-9_]+)", prompt_lower)
        if details_match:
            cname = details_match.group(1).capitalize()
            out, tr, _ = await self.execute_tool(
                tool_name="get_class_details",
                tool_args={"class_name": cname},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            if out.get("found") is False:
                return AgentRunResult(
                    agent_name=self.agent_name,
                    reply_text=f"No encontré la clase {cname} en el diagrama.",
                    traces=traces,
                    commands_executed=commands_executed,
                )
            detail = ClassDetail(**out)
            attrs = [f"{a.name}: {a.type}" for a in detail.attributes]
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=f"Clase {detail.name} tiene {len(attrs)} atributos: {', '.join(attrs)}.",
                traces=traces,
                commands_executed=commands_executed,
            )

        # 3. Consulta de directivas del Memory Bank
        if any(w in prompt_lower for w in ["convenciones", "directivas", "reglas de arquitectura", "memory bank", "memoria del proyecto"]):
            out, tr, _ = await self.execute_tool(
                tool_name="get_project_memory",
                tool_args={},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            mems = out.get("memories", [])
            if not mems:
                reply = "No hay directivas de arquitectura registradas aún para este proyecto."
            else:
                lines = [f"• [{m.get('category', '').upper()}] {m.get('directive')}" for m in mems]
                reply = "Directivas de arquitectura vigentes:\n" + "\n".join(lines)
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=reply,
                traces=traces,
                commands_executed=commands_executed,
            )

        # 4. Creación de clase (y relación si se solicita)
        create_match = re.search(r"(?:crea|agrega|añade|nueva)\s+(?:una\s+|un\s+)?(?:tabla|clase|entidad)\s+([a-zA-Z0-9_]+)", prompt_lower)
        if create_match:
            cname = create_match.group(1).capitalize()

            # Consultar Memory Bank para respetar directivas (ej. PK UUID)
            id_type = "INTEGER"
            mem_out, mem_tr, _ = await self.execute_tool(
                tool_name="get_project_memory",
                tool_args={},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(mem_tr)
            for m in mem_out.get("memories", []):
                if "uuid" in m.get("directive", "").lower():
                    id_type = "UUID"
                    break

            attrs = [{"name": "id", "type": id_type, "pk": True, "fk": False}]
            if "email" in prompt_lower:
                attrs.append({"name": "email", "type": "VARCHAR(255)", "pk": False, "fk": False})
            if "nombre" in prompt_lower:
                attrs.append({"name": "nombre", "type": "VARCHAR(255)", "pk": False, "fk": False})

            out, tr, cmd_res = await self.execute_tool(
                tool_name="execute_diagram_command",
                tool_args={
                    "command_type": "CREATE_CLASS",
                    "payload": {
                        "name": cname,
                        "attributes": attrs,
                        "position": {"x": 250, "y": 200},
                    },
                },
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            if cmd_res:
                commands_executed.append(cmd_res)

            # Verificar si se solicita relación con otra clase
            rel_target_match = re.search(r"(?:con\s+relaci[oó]n\s+a|relacionad[ao]\s+con)\s+([a-zA-Z0-9_]+)", prompt_lower)
            rel_reply_extra = ""
            if rel_target_match:
                target_cls = rel_target_match.group(1).capitalize()
                rel_out, rel_tr, rel_cmd_res = await self.execute_tool(
                    tool_name="execute_diagram_command",
                    tool_args={
                        "command_type": "CREATE_ASSOCIATION",
                        "payload": {
                            "source_entity_id": cname,
                            "target_entity_id": target_cls,
                            "association_type": "1:N",
                        },
                    },
                    db=db,
                    board_id=board_id,
                    user_id=user_id,
                )
                traces.append(rel_tr)
                if rel_cmd_res and rel_cmd_res.status == "success":
                    commands_executed.append(rel_cmd_res)
                    rel_reply_extra = f" y su relación con {target_cls}"

            # Emitir acción UI para resaltar la nueva entidad
            _, ui_tr, _ = await self.execute_tool(
                tool_name="emit_ui_action",
                tool_args={
                    "action_type": "highlight",
                    "target_id": cname,
                    "pulse_color": "emerald",
                    "message": f"Clase {cname} creada.",
                },
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(ui_tr)

            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=f"He creado la clase {cname}{rel_reply_extra} con éxito.",
                traces=traces,
                commands_executed=commands_executed,
            )

        # 4.b Edición / Actualización de clase
        edit_match = re.search(
            r"(?:edita|modifica|cambia|renombra)\s+(?:la\s+)?(?:tabla|clase|entidad)?\s*([a-zA-Z0-9_]+)\s+(?:a|por|para que se llame)\s+([a-zA-Z0-9_]+)",
            prompt_lower,
        )
        if edit_match:
            old_name = edit_match.group(1).capitalize()
            new_name = edit_match.group(2).capitalize()
            out, tr, cmd_res = await self.execute_tool(
                tool_name="execute_diagram_command",
                tool_args={
                    "command_type": "UPDATE_CLASS",
                    "payload": {
                        "class_name": old_name,
                        "entity_name": new_name,
                        "name": new_name,
                    },
                },
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            if cmd_res and cmd_res.status == "success":
                commands_executed.append(cmd_res)
                return AgentRunResult(
                    agent_name=self.agent_name,
                    reply_text=f"He actualizado la clase {old_name} para que se llame {new_name}.",
                    traces=traces,
                    commands_executed=commands_executed,
                )
            else:
                return AgentRunResult(
                    agent_name=self.agent_name,
                    reply_text=f"No pude actualizar la clase {old_name}: {out.get('error') or out.get('detail') or 'clase no encontrada'}.",
                    traces=traces,
                    commands_executed=commands_executed,
                )

        # 5. Creación de paquete
        pkg_match = re.search(r"(?:crea|agrega|añade|nuevo)\s+(?:un\s+)?paquete\s+([a-zA-Z0-9_]+)", prompt_lower)
        if pkg_match:
            pname = pkg_match.group(1)
            out, tr, cmd_res = await self.execute_tool(
                tool_name="create_package",
                tool_args={"name": pname},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            if cmd_res:
                commands_executed.append(cmd_res)
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=f"He creado el paquete '{pname}' con éxito.",
                traces=traces,
                commands_executed=commands_executed,
            )

        # 6. Redimensionar entidad
        resize_match = re.search(r"(?:redimensiona|ajusta tamaño de|cambia tamaño de)\s+([a-zA-Z0-9_]+)", prompt_lower)
        if resize_match:
            ename = resize_match.group(1)
            out, tr, cmd_res = await self.execute_tool(
                tool_name="resize_entity",
                tool_args={"entity_id": ename, "width": 260, "height": 180},
                db=db,
                board_id=board_id,
                user_id=user_id,
            )
            traces.append(tr)
            if cmd_res:
                commands_executed.append(cmd_res)
            return AgentRunResult(
                agent_name=self.agent_name,
                reply_text=f"He redimensionado la entidad '{ename}' a 260x180.",
                traces=traces,
                commands_executed=commands_executed,
            )


        return AgentRunResult(
            agent_name=self.agent_name,
            reply_text="Comprendido. No se requirieron acciones sobre el diagrama.",
            traces=traces,
            commands_executed=commands_executed,
        )
