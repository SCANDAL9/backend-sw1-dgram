"""
xmi_application_service.py — Application Service for XMI export, import, and preview workflows.
Orchestrates business logic between XmiRepository, XmiExporter, and XmiImporter without HTTP dependencies.
"""
from typing import Optional, Tuple
from app.generation.schema.repository.xmi_repository import XmiRepository
from app.generation.schema.service.xmi_service import XmiExporter, XmiImporter
from app.generation.schema.dto.xmi_dto import (
    XmiPreviewResponseDTO, XmiPreviewClassDTO, XmiPreviewAssociationDTO, XmiImportResponse
)
from app.generation.schema.exception.schema_exceptions import (
    BoardNotFoundException, XmiParsingError
)


class XmiApplicationService:
    def __init__(self, repo: XmiRepository):
        self.repo = repo

    async def export_board_xmi(
        self,
        board_id: str,
        selected_class_ids: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Exporta el modelo del tablero a formato XMI 2.1 compatible con Enterprise Architect.
        Retorna (xml_content, filename).
        """
        board = await self.repo.get_board(board_id)
        if not board:
            raise BoardNotFoundException("Board not found")

        project_id, package_id = await self.repo.ensure_project_and_package(board)
        await self.repo.commit()

        data = await self.repo.get_board_export_data(
            board=board,
            project_id=project_id,
            package_id=package_id,
            selected_class_ids=selected_class_ids,
        )

        exporter = XmiExporter()
        xml_content = exporter.export_board(
            project_name=board.name,
            board_name=board.name,
            classes=data["classes"],
            associations=data["associations"],
            board_elements=data["board_elements"],
            packages=data["packages"],
        )

        filename = f"{board.name.replace(' ', '_')}.xmi"
        return xml_content, filename

    async def preview_board_xmi(
        self,
        board_id: str,
        xml_str: str,
    ) -> XmiPreviewResponseDTO:
        """
        Inspección previa sin mutación: parsea el XMI y compara contra el estado del proyecto.
        """
        board = await self.repo.get_board(board_id)
        if not board:
            raise BoardNotFoundException("Board not found")

        project_id, _ = await self.repo.ensure_project_and_package(board)
        await self.repo.commit()

        importer = XmiImporter()
        try:
            parsed = importer.parse(xml_str)
        except Exception as e:
            raise XmiParsingError(f"Error al procesar XMI: {str(e)}")

        existing_classes = await self.repo.get_project_classes(project_id)
        existing_by_ext_ref = {c.external_ref: c for c in existing_classes if c.external_ref}
        existing_by_name = {c.name.lower(): c for c in existing_classes}

        classes_to_create: list[XmiPreviewClassDTO] = []
        classes_to_update: list[XmiPreviewClassDTO] = []
        warnings: list[str] = []
        parsed_class_ids = set()

        for cls in parsed.get("classes", []):
            c_name = cls.get("name")
            if not c_name:
                warnings.append("Se detectó una clase sin nombre en el XMI; será ignorada.")
                continue

            c_id = cls.get("id")
            parsed_class_ids.add(c_id)
            parsed_class_ids.add(c_name)

            ext_ref = cls.get("external_ref")
            existing_match = None
            if ext_ref and ext_ref in existing_by_ext_ref:
                existing_match = existing_by_ext_ref[ext_ref]
            elif c_name.lower() in existing_by_name:
                existing_match = existing_by_name[c_name.lower()]

            attr_names = [a.get("name", "attr") for a in cls.get("attributes", [])]
            action = "update" if existing_match else "create"

            dto = XmiPreviewClassDTO(
                name=c_name,
                external_ref=ext_ref,
                element_type=cls.get("element_type", "class"),
                is_abstract=cls.get("is_abstract", False),
                attributes_count=len(attr_names),
                attributes=attr_names,
                action=action,
            )

            if action == "update":
                classes_to_update.append(dto)
            else:
                classes_to_create.append(dto)

        preview_assocs: list[XmiPreviewAssociationDTO] = []
        for assoc in parsed.get("associations", []):
            src_raw = assoc.get("sourceId")
            tgt_raw = assoc.get("targetId")

            if src_raw not in parsed_class_ids or tgt_raw not in parsed_class_ids:
                warnings.append(
                    f"Relación '{assoc.get('name') or assoc.get('type')}' hace referencia a un clasificador no encontrado en el archivo."
                )
                continue

            preview_assocs.append(
                XmiPreviewAssociationDTO(
                    type=assoc.get("type", "Association"),
                    source_name=str(src_raw),
                    target_name=str(tgt_raw),
                    name=assoc.get("name"),
                    source_role=assoc.get("source_role"),
                    target_role=assoc.get("target_role"),
                    source_multiplicity=assoc.get("source_multiplicity"),
                    target_multiplicity=assoc.get("target_multiplicity"),
                )
            )

        return XmiPreviewResponseDTO(
            total_classes=len(classes_to_create) + len(classes_to_update),
            classes_to_create=classes_to_create,
            classes_to_update=classes_to_update,
            associations=preview_assocs,
            warnings=warnings,
        )

    async def import_board_xmi(
        self,
        board_id: str,
        xml_str: str,
        filename: str,
    ) -> Tuple[XmiImportResponse, Optional[dict]]:
        """
        Ejecuta la importación del archivo XMI con deduplicación activa, historial y snapshot.
        Retorna (XmiImportResponse, normalized_state).
        """
        board = await self.repo.get_board(board_id)
        if not board:
            raise BoardNotFoundException("Board not found")

        project_id, package_id = await self.repo.ensure_project_and_package(board)

        importer = XmiImporter()
        try:
            parsed = importer.parse(xml_str)
        except Exception as e:
            raise XmiParsingError(f"Error al procesar XMI: {str(e)}")

        result = await self.repo.persist_xmi_import(
            board=board,
            project_id=project_id,
            package_id=package_id,
            parsed=parsed,
            filename=filename,
        )

        created_classes = result["created_classes"]
        updated_classes = result["updated_classes"]
        imported_associations = result["imported_associations"]

        response = XmiImportResponse(
            status="success",
            message=(
                f"Se procesaron {len(created_classes) + len(updated_classes)} clases "
                f"({len(created_classes)} creadas, {len(updated_classes)} actualizadas) "
                f"y {imported_associations} relaciones."
            ),
            classes=created_classes,
            updated_classes=updated_classes,
            associations_count=imported_associations,
        )

        return response, result["normalized_state"]
