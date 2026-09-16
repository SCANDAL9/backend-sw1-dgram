def apply_relation_command(relations: dict, command_type: str, payload: dict) -> None:
    """Apply a relation-related command to the in-memory relation store."""

    match command_type:
        case "CREATE_RELATION":
            rel_id = payload.get("relation_id") or f"rel-{len(relations) + 1}"
            relations[rel_id] = {
                "id": rel_id,
                "source_id": payload.get("source_entity_id"),
                "target_id": payload.get("target_entity_id"),
                "type": payload.get("relation_type", "1:N"),
                "source_column": payload.get("source_column", ""),
                "target_column": payload.get("target_column", ""),
            }

        case "DELETE_RELATION":
            rel_id = payload.get("relation_id") or payload.get("entity_id")
            relations.pop(rel_id, None)

        case "UPDATE_RELATION":
            rel_id = payload.get("relation_id") or payload.get("entity_id")
            if rel_id in relations:
                if payload.get("relation_type"):
                    relations[rel_id]["type"] = payload["relation_type"]
                if payload.get("source_column") is not None:
                    relations[rel_id]["source_column"] = payload["source_column"]
                if payload.get("target_column") is not None:
                    relations[rel_id]["target_column"] = payload["target_column"]

        case "LINK_ASSOCIATION_CLASS":
            rel_id = payload.get("relation_id") or payload.get("association_id")
            class_id = payload.get("class_id") or payload.get("entity_id")
            if rel_id in relations and class_id:
                relations[rel_id]["association_class_id"] = class_id

        case "UNLINK_ASSOCIATION_CLASS":
            rel_id = payload.get("relation_id") or payload.get("association_id")
            if rel_id in relations:
                relations[rel_id].pop("association_class_id", None)