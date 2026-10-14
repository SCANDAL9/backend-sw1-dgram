from typing import Any


def apply_entity_command(entities: dict, command_type: str, payload: dict) -> None:
    """Apply an entity-related command to the in-memory entity store."""

    entity_id = payload.get("entity_id")

    match command_type:
        case "CREATE_ENTITY":
            cols = payload.get("columns")
            if cols is None:
                cols = payload.get("attributes")
            if cols is None:
                cols = []
            entities[entity_id] = {
                "id": entity_id,
                "name": payload.get("entity_name") or payload.get("class_name") or "Entity",
                "columns": list(cols),
                "position": payload.get("position") or {"x": 100, "y": 100},
                "width": payload.get("width"),
                "height": payload.get("height"),
                "package_id": payload.get("package_id"),
                "element_type": payload.get("element_type", "class"),
                "is_abstract": bool(payload.get("is_abstract", False)),
            }

        case "DELETE_ENTITY" | "DETACH_ENTITY":
            entities.pop(entity_id, None)

        case "UPDATE_ENTITY":
            if entity_id in entities:
                if payload.get("entity_name"):
                    entities[entity_id]["name"] = payload["entity_name"]
                if payload.get("columns") is not None:
                    entities[entity_id]["columns"] = list(payload["columns"])
                elif payload.get("attributes") is not None:
                    entities[entity_id]["columns"] = list(payload["attributes"])
                if payload.get("package_id") is not None:
                    entities[entity_id]["package_id"] = payload["package_id"]
                if payload.get("element_type") is not None:
                    entities[entity_id]["element_type"] = payload["element_type"]
                if "is_abstract" in payload:
                    entities[entity_id]["is_abstract"] = bool(payload["is_abstract"])

        case "MOVE_ENTITY":
            if entity_id in entities:
                entities[entity_id]["position"] = payload.get("position", {"x": 0, "y": 0})

        case "RESIZE_ENTITY" | "RESIZE_CLASS":
            if entity_id in entities:
                if payload.get("width") is not None:
                    entities[entity_id]["width"] = float(payload["width"])
                if payload.get("height") is not None:
                    entities[entity_id]["height"] = float(payload["height"])

        case "ASSIGN_CLASS_PACKAGE":
            if entity_id in entities and payload.get("package_id"):
                entities[entity_id]["package_id"] = payload["package_id"]

        case "ADD_COLUMN":
            if entity_id in entities:
                if entities[entity_id].get("columns") is None:
                    entities[entity_id]["columns"] = []
                col = payload.get("column") or payload.get("column_changes") or payload.get("attribute_changes") or {}
                entities[entity_id]["columns"].append(col)

        case "UPDATE_COLUMN":
            if entity_id in entities:
                col_name = payload.get("column_name")
                changes = payload.get("column_changes", {})
                for col in entities[entity_id]["columns"]:
                    if col.get("name") == col_name:
                        col.update(changes)
                        if "isDerived" in changes:
                            col["is_derived"] = changes["isDerived"]
                        if "is_derived" in changes:
                            col["isDerived"] = changes["is_derived"]
                        if "defaultValue" in changes:
                            col["default_value"] = changes["defaultValue"]
                        if "default_value" in changes:
                            col["defaultValue"] = changes["default_value"]

        case "DELETE_COLUMN":
            if entity_id in entities:
                col_name = payload.get("column_name")
                entities[entity_id]["columns"] = [
                    c for c in entities[entity_id]["columns"] if c.get("name") != col_name
                ]

        case "REORDER_ATTRIBUTES":
            if entity_id in entities:
                ordered_names = payload.get("ordered_attribute_names") or payload.get("ordered_names") or []
                if ordered_names:
                    current_cols = entities[entity_id].get("columns", [])
                    col_map = {c.get("name"): c for c in current_cols}
                    new_cols = []
                    for name in ordered_names:
                        if name in col_map:
                            new_cols.append(col_map.pop(name))
                    new_cols.extend(col_map.values())
                    entities[entity_id]["columns"] = new_cols
