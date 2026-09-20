import uuid
from app.modeling.diagram.dto.command_dto import Command
from app.modeling.diagram.dto.command_dto import CommandResult
from app.modeling.diagram.service.entity_applier_service import apply_entity_command
from app.modeling.diagram.service.relation_applier_service import apply_relation_command
from app.workspace.history.service.command_history_service import CommandHistory

ENTITY_COMMANDS = {
    "CREATE_ENTITY", "DELETE_ENTITY", "UPDATE_ENTITY", "MOVE_ENTITY",
    "ADD_COLUMN", "UPDATE_COLUMN", "DELETE_COLUMN",
    "CREATE_CLASS", "DELETE_CLASS", "UPDATE_CLASS", "MOVE_CLASS",
    "ADD_ATTRIBUTE", "UPDATE_ATTRIBUTE", "DELETE_ATTRIBUTE",
    "RESIZE_ENTITY", "RESIZE_CLASS", "ASSIGN_CLASS_PACKAGE",
}

RELATION_COMMANDS = {
    "CREATE_RELATION", "UPDATE_RELATION", "DELETE_RELATION",
    "CREATE_ASSOCIATION", "UPDATE_ASSOCIATION", "DELETE_ASSOCIATION",
    "LINK_ASSOCIATION_CLASS", "UNLINK_ASSOCIATION_CLASS",
}

PACKAGE_COMMANDS = {
    "CREATE_PACKAGE", "UPDATE_PACKAGE", "DELETE_PACKAGE",
}

# Map UML → ER para normalizar payload antes de aplicar
_ENTITY_ALIAS = {
    "CREATE_CLASS": "CREATE_ENTITY", "DELETE_CLASS": "DELETE_ENTITY",
    "UPDATE_CLASS": "UPDATE_ENTITY", "MOVE_CLASS": "MOVE_ENTITY",
    "ADD_ATTRIBUTE": "ADD_COLUMN", "UPDATE_ATTRIBUTE": "UPDATE_COLUMN",
    "DELETE_ATTRIBUTE": "DELETE_COLUMN",
    "RESIZE_CLASS": "RESIZE_ENTITY",
}
_RELATION_ALIAS = {
    "CREATE_ASSOCIATION": "CREATE_RELATION", "UPDATE_ASSOCIATION": "UPDATE_RELATION",
    "DELETE_ASSOCIATION": "DELETE_RELATION",
}


def check_generalization_cycle(relations: dict, source_id: str, target_id: str, exclude_rel_id: str | None = None) -> bool:
    """Verifica si agregar/actualizar una relación de herencia source_id -> target_id crearía un ciclo."""
    if source_id == target_id:
        return True

    gen_types = {"generalization", "realization", "inheritance"}
    visited = set()
    queue = [target_id]

    while queue:
        curr = queue.pop(0)
        if curr == source_id:
            return True
        visited.add(curr)
        for rid, r in relations.items():
            if rid == exclude_rel_id:
                continue
            rtype = str(r.get("type", "")).lower()
            if any(gt in rtype for gt in gen_types):
                if r.get("source_id") == curr and r.get("target_id") not in visited:
                    queue.append(r.get("target_id"))

    return False


class CommandHandler:
    """Processes commands against the in-memory DatabaseModel and persists history."""

    def __init__(self, board_id: str, history: CommandHistory):
        self.board_id = board_id
        self.history = history
        self.version = 0
        self.entities: dict = {}
        self.relations: dict = {}
        self.packages: dict = {}

    async def execute(self, command: Command) -> CommandResult:
        try:
            command.model_version = self.version + 1
            await self.history.push(command)
            self._apply(command)
            self.version = command.model_version

            return CommandResult(
                success=True,
                command_id=command.command_id,
                new_model_version=self.version,
            )
        except Exception as e:
            return CommandResult(
                success=False,
                command_id=command.command_id,
                error=str(e),
            )

    def _normalize_payload(self, payload: dict) -> dict:
        # UML → ER aliases so handlers stay ER-only
        if payload.get("class_id") and not payload.get("entity_id"):
            payload["entity_id"] = payload["class_id"]
        if payload.get("class_name") and not payload.get("entity_name"):
            payload["entity_name"] = payload["class_name"]
        if payload.get("attributes") and not payload.get("columns"):
            payload["columns"] = payload["attributes"]
        if payload.get("attribute_name") and not payload.get("column_name"):
            payload["column_name"] = payload["attribute_name"]
        if payload.get("attribute_changes") and not payload.get("column_changes"):
            payload["column_changes"] = payload["attribute_changes"]
        if payload.get("source_class_id") and not payload.get("source_entity_id"):
            payload["source_entity_id"] = payload["source_class_id"]
        if payload.get("target_class_id") and not payload.get("target_entity_id"):
            payload["target_entity_id"] = payload["target_class_id"]
        if payload.get("source_id") and not payload.get("source_entity_id"):
            payload["source_entity_id"] = payload["source_id"]
        if payload.get("target_id") and not payload.get("target_entity_id"):
            payload["target_entity_id"] = payload["target_id"]
        if payload.get("association_type") and not payload.get("relation_type"):
            payload["relation_type"] = payload["association_type"]
        if payload.get("source_attribute") and not payload.get("source_column"):
            payload["source_column"] = payload["source_attribute"]
        if payload.get("target_attribute") and not payload.get("target_column"):
            payload["target_column"] = payload["target_attribute"]
        if payload.get("association_id") and not payload.get("relation_id"):
            payload["relation_id"] = payload["association_id"]
        return payload

    def _apply(self, command: Command) -> None:
        raw_type = command.command_type.value if hasattr(command.command_type, "value") else str(command.command_type)
        cmd_type = _ENTITY_ALIAS.get(raw_type, _RELATION_ALIAS.get(raw_type, raw_type))
        payload = self._normalize_payload(command.payload.model_dump())

        if raw_type in ENTITY_COMMANDS or cmd_type in ENTITY_COMMANDS:
            apply_entity_command(self.entities, cmd_type, payload)

        if raw_type in RELATION_COMMANDS or cmd_type in RELATION_COMMANDS:
            if cmd_type == "CREATE_RELATION":
                src = payload.get("source_entity_id")
                tgt = payload.get("target_entity_id")
                if not src or not tgt or src not in self.entities or tgt not in self.entities:
                    raise ValueError(f"Cannot create relation: endpoints '{src}' and '{tgt}' must both exist as entities")

                rel_type = str(payload.get("relation_type", "")).lower()
                if any(gt in rel_type for gt in ("generalization", "realization", "inheritance")):
                    if check_generalization_cycle(self.relations, src, tgt):
                        raise ValueError(f"Cyclic inheritance detected: '{src}' cannot inherit from '{tgt}'")

            elif cmd_type == "UPDATE_RELATION":
                rel_id = payload.get("relation_id") or payload.get("entity_id")
                existing = self.relations.get(rel_id)
                if existing:
                    rel_type = str(payload.get("relation_type") or existing.get("type", "")).lower()
                    if any(gt in rel_type for gt in ("generalization", "realization", "inheritance")):
                        src = existing.get("source_id")
                        tgt = existing.get("target_id")
                        if src and tgt and check_generalization_cycle(self.relations, src, tgt, exclude_rel_id=rel_id):
                            raise ValueError(f"Cyclic inheritance detected: '{src}' cannot inherit from '{tgt}'")

            apply_relation_command(self.relations, cmd_type, payload)

        if raw_type in PACKAGE_COMMANDS:
            if raw_type == "CREATE_PACKAGE":
                pkg_id = payload.get("package_id") or payload.get("id") or str(uuid.uuid4())
                self.packages[pkg_id] = {
                    "id": pkg_id,
                    "name": payload.get("package_name") or payload.get("name") or "Nuevo Paquete",
                }
            elif raw_type == "UPDATE_PACKAGE":
                pkg_id = payload.get("package_id") or payload.get("id")
                if pkg_id in self.packages:
                    new_name = payload.get("package_name") or payload.get("name")
                    if new_name:
                        self.packages[pkg_id]["name"] = new_name
            elif raw_type == "DELETE_PACKAGE":
                pkg_id = payload.get("package_id") or payload.get("id")
                self.packages.pop(pkg_id, None)
                for e in self.entities.values():
                    if e.get("package_id") == pkg_id:
                        e["package_id"] = "default"

        if cmd_type == "DELETE_ENTITY":
            eid = payload.get("entity_id") or command.payload.entity_id or command.payload.class_id
            if eid:
                self.relations = {
                    k: v for k, v in self.relations.items()
                    if v.get("source_id") != eid and v.get("target_id") != eid
                }

    def apply_remote_command(self, command: Command) -> None:
        """Applies a command executed on another replica to local memory without re-persisting history."""
        self._apply(command)
        if command.model_version is not None and command.model_version > 0:
            self.version = max(self.version, command.model_version)
        else:
            self.version += 1

    async def undo(self) -> None:
        await self.history.undo()
        await self._rebuild()

    async def redo(self) -> None:
        await self.history.redo()
        await self._rebuild()

    async def rollback_last_command(self) -> None:
        if self.history._cached_commands:
            self.history._cached_commands.pop()
            self.history._pointer = len(self.history._cached_commands) - 1
        await self._rebuild()

    async def _rebuild(self) -> None:
        self.entities.clear()
        self.relations.clear()
        self.packages.clear()
        self.version = 0
        for cmd in await self.history.get_all(upto_pointer=True):
            self._apply(cmd)
            self.version = cmd.model_version

    def get_state(self) -> dict:
        entities = []
        for e in self.entities.values():
            columns = e.get("columns") or e.get("attributes") or []
            entities.append({
                "id": e.get("id"),
                "name": e.get("name"),
                "attributes": columns,
                "columns": columns,
                "position": e.get("position", {"x": 100, "y": 100}),
                "width": e.get("width"),
                "height": e.get("height"),
                "package_id": e.get("package_id"),
                "packageId": e.get("package_id"),
                "element_type": e.get("element_type", "class"),
                "elementType": e.get("element_type", "class"),
                "is_abstract": bool(e.get("is_abstract", False)),
                "isAbstract": bool(e.get("is_abstract", False)),
            })

        relations = []
        for r in self.relations.values():
            relations.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "sourceId": r.get("source_id"),
                "targetId": r.get("target_id"),
                "type": r.get("type", "1:N"),
                "sourceColumn": r.get("source_column", ""),
                "targetColumn": r.get("target_column", ""),
                "sourceRole": r.get("source_role"),
                "targetRole": r.get("target_role"),
                "sourceMultiplicity": r.get("source_multiplicity"),
                "targetMultiplicity": r.get("target_multiplicity"),
                # UML aliases
                "sourceClassId": r.get("source_id"),
                "targetClassId": r.get("target_id"),
                "sourceAttribute": r.get("source_column", ""),
                "targetAttribute": r.get("target_column", ""),
                "associationClassId": r.get("association_class_id"),
            })

        return {
            "entities": entities,
            "relations": relations,
            "classes": entities,
            "associations": relations,
            "packages": list(self.packages.values()),
            "version": self.version,
        }

    def load_snapshot(self, state: dict) -> None:
        """Populate in-memory stores from a persisted camelCase snapshot. Accepts entities/classes, relations/associations."""
        self.entities = {}
        self.relations = {}
        self.packages = {}

        raw_packages = state.get("packages", [])
        if isinstance(raw_packages, list):
            for p in raw_packages:
                if isinstance(p, dict) and "id" in p:
                    self.packages[p["id"]] = {
                        "id": p["id"],
                        "name": p.get("name", "Paquete"),
                    }

        raw_entities = state.get("entities", []) or state.get("classes", [])
        raw_relations = state.get("relations", []) or state.get("associations", [])
        for index, e in enumerate(raw_entities):
            eid = e.get("id") or f"entity-{index + 1}"
            self.entities[eid] = {
                "id": eid,
                "name": e.get("name", ""),
                "columns": e.get("attributes", []) or e.get("columns", []) or [],
                "position": e.get("position", {"x": 100, "y": 100}),
                "width": e.get("width"),
                "height": e.get("height"),
                "package_id": e.get("package_id") or e.get("packageId"),
                "element_type": e.get("element_type") or e.get("elementType", "class"),
                "is_abstract": bool(e.get("is_abstract") or e.get("isAbstract", False)),
            }
        for index, r in enumerate(raw_relations):
            rid = r.get("id") or f"rel-{index + 1}"
            self.relations[rid] = {
                "id": rid,
                "name": r.get("name"),
                "source_id": r.get("sourceId") or r.get("sourceClassId") or r.get("source_id"),
                "target_id": r.get("targetId") or r.get("targetClassId") or r.get("target_id"),
                "type": r.get("type", "1:N"),
                "source_column": r.get("sourceColumn") or r.get("sourceAttribute") or r.get("source_column") or "",
                "target_column": r.get("targetColumn") or r.get("targetAttribute") or r.get("target_column") or "",
                "source_role": r.get("sourceRole") or r.get("source_role"),
                "target_role": r.get("targetRole") or r.get("target_role"),
                "source_multiplicity": r.get("sourceMultiplicity") or r.get("source_multiplicity"),
                "target_multiplicity": r.get("targetMultiplicity") or r.get("target_multiplicity"),
                "association_class_id": r.get("associationClassId") or r.get("association_class_id"),
            }
        self.version = int(state.get("version", 0))
