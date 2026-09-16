from typing import Any


def apply_entity_command(entities: dict, command_type: str, payload: dict) -> None:
    """Apply an entity-related command to the in-memory entity store."""

    entity_id = payload.get("entity_id")

    match command_type:
        case "CREATE_ENTITY":
            entities[entity_id] = {
                "id": entity_id,
                "name": payload.get("entity_name"),
                "columns": payload.get("columns", []),
                "position": payload.get("position", {"x": 100, "y": 100}),
            }

        case "DELETE_ENTITY":
            entities.pop(entity_id, None)

        case "UPDATE_ENTITY":
            if entity_id in entities:
                if payload.get("entity_name"):
                    entities[entity_id]["name"] = payload["entity_name"]
                if payload.get("columns") is not None:
                    entities[entity_id]["columns"] = payload["columns"]

        case "MOVE_ENTITY":
            if entity_id in entities:
                entities[entity_id]["position"] = payload.get("position", {"x": 0, "y": 0})

        case "ADD_COLUMN":
            if entity_id in entities:
                entities[entity_id]["columns"].append(payload.get("column_changes", {}))

        case "UPDATE_COLUMN":
            if entity_id in entities:
                col_name = payload.get("column_name")
                changes = payload.get("column_changes", {})
                for col in entities[entity_id]["columns"]:
                    if col.get("name") == col_name:
                        col.update(changes)

        case "DELETE_COLUMN":
            if entity_id in entities:
                col_name = payload.get("column_name")
                entities[entity_id]["columns"] = [
                    c for c in entities[entity_id]["columns"] if c.get("name") != col_name
                ]
