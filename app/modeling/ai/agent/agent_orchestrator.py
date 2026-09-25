"""
agent_orchestrator.py — Orquestador de Agentes Inteligentes con Google ADK para dgram.
Enruta solicitudes del usuario hacia el agente especializado correcto:
  - DiagramAgent: Modelado UML/ER, consultas de estructura y mutación vía Command Protocol.
  - GuideAgent: Mentoría contextual, explicación de interfaz y acciones visuales en el cliente.
  - CodeGenAgent: Generación de código Spring Boot 3.3.x (Java 21, JPA/Hibernate, Lombok).

Registra trazas estructuradas (AgentExecutionTrace) y evita bucles o traspasos redundantes.
"""
import uuid
import logging
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modeling.ai.entity.chat_entity import ChatConversation, ChatMessage, AiAction, ActionStatus, ActorTypeEnum
from app.modeling.ai.agent.adk_runner import ADKAgentRunner, AgentRunResult, AgentExecutionTrace
from app.modeling.ai.agent.agent_session import session_state_manager
from app.modeling.ai.service.ai_service import get_or_create_conversation
from app.core.websocket.manager import manager

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    DIAGRAM = "DiagramAgent"
    GUIDE = "GuideAgent"
    CODEGEN = "CodeGenAgent"


class OrchestratorResponse(BaseModel):
    agent: str
    reply: str
    traces: list[AgentExecutionTrace] = Field(default_factory=list)
    commands_executed: list[dict[str, Any]] = Field(default_factory=list)
    conversation_id: str


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS ESPECIALIZADOS DE AGENTES
# ─────────────────────────────────────────────────────────────────────────────

DIAGRAM_AGENT_PROMPT = """Eres el DiagramAgent de dgram, un arquitecto de software senior y especialista en diseño de bases de datos y UML.
Tu responsabilidad es ayudar a modelar entidades, clases, atributos y relaciones con consistencia relacional estricta.

REGLAS OBLIGATORIAS:
1. ANTES de realizar cualquier afirmación sobre una entidad, consulta los datos reales con 'get_class_details' o 'get_diagram_summary'.
2. Para crear o modificar clases, atributos o relaciones, utiliza 'execute_diagram_command'.
3. NUNCA inventes nombres de tablas o relaciones sin verificar el estado actual.
4. Si el usuario hace una consulta conceptual o pide sugerencias de normalización, responde con análisis técnico fundamentado sin mutar el diagrama hasta que te dé una instrucción directa.
5. Puedes usar 'emit_ui_action' para resaltar elementos en los que acabas de operar.
"""

GUIDE_AGENT_PROMPT = """Eres el GuideAgent de dgram, un mentor interactivo y guía de la aplicación.
Tu misión es orientar al usuario sobre el uso de la plataforma, la barra de herramientas, los atajos de teclado y las buenas prácticas de diseño de software.

REGLAS OBLIGATORIAS:
1. Explica los elementos de la interfaz de forma clara, motivadora y concisa.
2. Si el usuario pregunta por un botón, herramienta o sección de la pantalla, utiliza 'emit_ui_action' con acción 'highlight' o 'focus' para señalarle visualmente el elemento al usuario en tiempo real.
3. No ejecutes mutaciones de base de datos directamente; tu rol es de guía y mentoría.
"""

CODEGEN_AGENT_PROMPT = """Eres el CodeGenAgent de dgram, un ingeniero senior backend especializado 100% en Spring Boot 3.3.x y Java 21.
Tu responsabilidad es transformar el diagrama UML en código de producción limpio y robusto para Spring Boot.

REGLAS OBLIGATORIAS:
1. Utiliza SIEMPRE Java 21 y Spring Boot 3.3.x con Spring Data JPA y Hibernate 6.
2. Utiliza anotaciones de Lombok: @Getter, @Setter, @NoArgsConstructor, @AllArgsConstructor, @Builder (evita @Data en entidades JPA para prevenir problemas con equals/hashCode y lazy loading).
3. Todas las entidades deben tener @Entity, @Table(name = "..."), y una clave primaria con @Id y @GeneratedValue.
4. Mapea relaciones correctamente: @ManyToOne con @JoinColumn, @OneToMany con mappedBy, @ManyToMany con @JoinTable.
5. Genera DTOs (records de Java 21), Spring Data Repositories, Interfaces de Servicio, Implementaciones y RestControllers con OpenAPI/Swagger.
6. Consulta el estado real del diagrama con 'get_class_details' o 'get_diagram_summary' antes de generar el código.
"""


class AgentOrchestrator:
    """
    Orquestador central que clasifica la intención y delega al agente correspondiente.
    """

    @staticmethod
    def classify_intent(prompt: str) -> AgentType:
        """
        Determina qué agente debe atender el mensaje según la intención detectada.
        """
        p = prompt.lower()

        # 1. CodeGen Agent: generación de código backend
        codegen_keywords = [
            "spring", "spring boot", "springboot", "java", "jpa", "entidad java",
            "código", "codigo", "controller", "repository", "generar codigo",
            "generar clases", "backend", "lombok", "generame el codigo"
        ]
        if any(k in p for k in codegen_keywords):
            return AgentType.CODEGEN

        # 2. Guide Agent: ayuda de interfaz, uso de herramientas, guía
        guide_keywords = [
            "cómo uso", "como uso", "para qué sirve", "para que sirve", "ayuda",
            "dónde está", "donde esta", "cómo creo", "como creo", "burbuja",
            "tutorial", "guía", "guia", "atajo", "keyboard", "teclado", "toolbar"
        ]
        # Distinguir entre "cómo creo una clase" (pregunta de guía) vs "crea una clase Cliente" (orden de modelado)
        if any(k in p for k in guide_keywords) and not any(verb in p for verb in ["crea una clase", "agrega la tabla", "elimina la relación", "añade un atributo"]):
            return AgentType.GUIDE

        # 3. Diagram Agent: por defecto para modelado, diseño y preguntas de arquitectura UML
        return AgentType.DIAGRAM

    async def route_and_execute(
        self,
        db: AsyncSession,
        board_id: str,
        user_prompt: str,
        user_id: str | None = None,
        force_agent: AgentType | None = None,
        conversation_id: str | None = None,
    ) -> OrchestratorResponse:
        """
        Enruta la solicitud al agente adecuado, ejecuta el ciclo de tools y persiste la auditoría.
        """
        agent_type = force_agent or self.classify_intent(user_prompt)

        # 1. Obtener o crear conversación de chat
        persisted_user_id = (
            user_id
            if user_id
            and not str(user_id).startswith("guest")
            and not str(user_id).startswith("user-")
            and str(user_id) not in {"system", "demo", "public", "user-test"}
            else None
        )
        conv = await get_or_create_conversation(
            db, board_id, persisted_user_id, conversation_id=conversation_id
        )
        conv_id = str(conv.id)

        # Guardar mensaje del usuario
        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            sender_type=ActorTypeEnum.user,
            user_id=persisted_user_id,
            content_text=user_prompt,
        )
        db.add(user_msg)
        await db.flush()

        # 2. Obtener estado temporal de sesión del usuario (selected_element, viewport, active_tool)
        session_state = session_state_manager.get_session(board_id, user_id)

        # 3. Configurar y lanzar el agente especializado
        if agent_type == AgentType.GUIDE:
            runner = ADKAgentRunner(agent_name=AgentType.GUIDE.value)
            system_prompt = GUIDE_AGENT_PROMPT
        elif agent_type == AgentType.CODEGEN:
            runner = ADKAgentRunner(agent_name=AgentType.CODEGEN.value)
            system_prompt = CODEGEN_AGENT_PROMPT
        else:
            runner = ADKAgentRunner(agent_name=AgentType.DIAGRAM.value)
            system_prompt = DIAGRAM_AGENT_PROMPT

        run_result: AgentRunResult = await runner.run(
            db=db,
            board_id=board_id,
            user_prompt=user_prompt,
            user_id=user_id,
            system_instruction=system_prompt,
            session_state=session_state,
        )

        # 4. Guardar respuesta del agente en ChatMessage
        ai_msg = ChatMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            sender_type=ActorTypeEnum.ai,
            user_id=None,
            content_text=run_result.reply_text,
        )
        db.add(ai_msg)
        await db.flush()

        # 5. Persistir cada traza en AiAction (Auditoría de ejecución sin CoT)
        commands_payloads = []
        for trace in run_result.traces:
            action = AiAction(
                id=str(uuid.uuid4()),
                chat_message_id=ai_msg.id,
                function_name=trace.action_name,
                function_arguments=trace.input_payload,
                status=ActionStatus.success if trace.status == "success" else ActionStatus.failed,
            )
            db.add(action)

        for cmd in run_result.commands_executed:
            commands_payloads.append(cmd.model_dump())

        await db.commit()

        # 6. Notificar a clientes WebSocket si se ejecutaron comandos
        if commands_payloads:
            try:
                await manager.broadcast(
                    board_id=board_id,
                    message={
                        "type": "agent:commands_executed",
                        "data": {
                            "agent": run_result.agent_name,
                            "commands": commands_payloads,
                        },
                    },
                )
            except Exception as e:
                logger.warning("Error notificando comandos por WebSocket: %s", e)

        return OrchestratorResponse(
            agent=run_result.agent_name,
            reply=run_result.reply_text,
            traces=run_result.traces,
            commands_executed=commands_payloads,
            conversation_id=conv.id,
        )


agent_orchestrator = AgentOrchestrator()
