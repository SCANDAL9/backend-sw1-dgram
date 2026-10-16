"""
xmi_repository.py — Data Access Layer for XMI export, import, and deduplication.
Encapsulates all SQLAlchemy queries and persistence operations for UML board elements,
classes, batched attributes (eradicating N+1 queries), associations, history, and snapshots.
"""
import uuid
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.diagram.entity.board_entity import Board
from app.modeling.diagram.entity.board_normalized_entity import (
    BoardElement, BoardHistory, BoardSnapshot, ActorTypeEnum
)
from app.modeling.diagram.entity.uml_entity import (
    Package, ClassElement, Attribute, Association, AssociationClassLink,
    ClassifierType, VisibilityEnum, AssociationType, ClassSource
)
from app.modeling.diagram.service.relational_mutator_service import ensure_project_and_package
from app.generation.schema.mapper.schema_mapper import SchemaMapper
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state


class XmiRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_board(self, board_id: str) -> Optional[Board]:
        """Recupera un tablero por su identificador primario."""
        return await self.db.get(Board, board_id)

    async def ensure_project_and_package(self, board: Board) -> Tuple[str, str]:
        """Asegura que el tablero tenga proyecto y paquete contenedor."""
        return await ensure_project_and_package(self.db, board)

    async def commit(self) -> None:
        """Confirma la transacción actual en la base de datos."""
        await self.db.commit()

    async def get_board_export_data(
        self,
        board: Board,
        project_id: str,
        package_id: str,
        selected_class_ids: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Recupera elementos del tablero, clases, atributos batch (sin N+1),
        asociaciones y paquetes necesarios para la serialización a XMI.
        """
        board_id = board.id

        # 1. Obtener elementos gráficos en el tablero
        be_stmt = select(BoardElement).where(BoardElement.board_id == board_id)
        be_res = await self.db.execute(be_stmt)
        board_elements = be_res.scalars().all()

        board_element_map = {
            be.class_id: {"x": be.x, "y": be.y, "w": be.width or 220.0, "h": be.height or 160.0}
            for be in board_elements
        }

        # 2. Obtener clases asociadas al proyecto/tablero
        class_ids = list(board_element_map.keys())
        if not class_ids:
            cls_stmt = select(ClassElement).where(ClassElement.package_id == package_id)
            cls_res = await self.db.execute(cls_stmt)
            classes_db = list(cls_res.scalars().all())
        else:
            cls_stmt = select(ClassElement).where(ClassElement.id.in_(class_ids))
            cls_res = await self.db.execute(cls_stmt)
            classes_db = list(cls_res.scalars().all())

        if selected_class_ids and isinstance(selected_class_ids, str):
            filter_set = {cid.strip() for cid in selected_class_ids.split(",") if cid.strip()}
            classes_db = [c for c in classes_db if c.id in filter_set]

        # 3. Batch query attributes para eliminar el problema N+1
        classes_payload = []
        if classes_db:
            target_cids = [c.id for c in classes_db]
            attr_stmt = (
                select(Attribute)
                .where(Attribute.class_id.in_(target_cids))
                .order_by(Attribute.class_id, Attribute.order_index)
            )
            attr_res = await self.db.execute(attr_stmt)
            all_attrs = attr_res.scalars().all()

            attrs_by_class: Dict[str, List[Attribute]] = {cid: [] for cid in target_cids}
            for a in all_attrs:
                if a.class_id in attrs_by_class:
                    attrs_by_class[a.class_id].append(a)

            for c in classes_db:
                attrs = attrs_by_class.get(c.id, [])
                pos = dict(board_element_map.get(c.id, {"x": 100.0, "y": 100.0, "w": 200.0, "h": 70.0}))
                num_attrs = len(attrs)
                dynamic_h = max(56.0, 56.0 + (num_attrs * 18.0))
                if pos.get("h") in (None, 160.0):
                    pos["h"] = dynamic_h
                board_element_map[c.id] = pos
                classes_payload.append(SchemaMapper.class_to_dict(c, attrs, pos))

        # 4. Obtener asociaciones
        if classes_payload:
            c_ids = [c["id"] for c in classes_payload]
            assoc_stmt = select(Association).where(
                Association.source_class_id.in_(c_ids),
                Association.target_class_id.in_(c_ids),
            )
            assoc_res = await self.db.execute(assoc_stmt)
            associations_db = assoc_res.scalars().all()
            assoc_ids = [a.id for a in associations_db]

            assoc_class_map = {}
            if assoc_ids:
                acl_stmt = select(AssociationClassLink).where(AssociationClassLink.association_id.in_(assoc_ids))
                acl_res = await self.db.execute(acl_stmt)
                for acl in acl_res.scalars().all():
                    assoc_class_map[acl.association_id] = acl.class_id

            assoc_payload = []
            for a in associations_db:
                ad = SchemaMapper.association_to_dict(a)
                if a.id in assoc_class_map:
                    ad["association_class_id"] = assoc_class_map[a.id]
                if not ad.get("source_multiplicity") and not ad.get("target_multiplicity"):
                    if ad.get("association_class_id"):
                        ad["source_multiplicity"] = "0..*"
                        ad["target_multiplicity"] = "0..*"
                    else:
                        rel_t = str(ad.get("type", "")).lower()
                        if rel_t in ("association", "aggregation", "composition"):
                            ad["source_multiplicity"] = "1"
                            ad["target_multiplicity"] = "0..*"
                elif ad.get("association_class_id"):
                    if not ad.get("source_multiplicity"):
                        ad["source_multiplicity"] = "0..*"
                    if not ad.get("target_multiplicity"):
                        ad["target_multiplicity"] = "0..*"
                assoc_payload.append(ad)
        else:
            assoc_payload = []

        # 5. Obtener paquetes del proyecto para conservar jerarquía en XMI
        pkg_stmt = select(Package).where(Package.project_id == project_id)
        pkg_res = await self.db.execute(pkg_stmt)
        raw_pkgs = pkg_res.scalars().all()
        if len(raw_pkgs) == 1 and raw_pkgs[0].name.lower() in ("default", "logical view"):
            packages_payload = []
        else:
            packages_payload = [{"id": p.id, "name": p.name} for p in raw_pkgs if p.name.lower() not in ("default", "logical view")]

        return {
            "classes": classes_payload,
            "associations": assoc_payload,
            "board_elements": board_element_map,
            "packages": packages_payload,
        }

    async def get_project_classes(self, project_id: str) -> List[ClassElement]:
        """Obtiene todas las clases del proyecto uniendo con sus paquetes correspondientes."""
        stmt = (
            select(ClassElement)
            .join(Package, ClassElement.package_id == Package.id)
            .where(Package.project_id == project_id)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_project_packages(self, project_id: str) -> List[Package]:
        """Obtiene todos los paquetes asociados a un proyecto."""
        pkg_stmt = select(Package).where(Package.project_id == project_id)
        pkg_res = await self.db.execute(pkg_stmt)
        return list(pkg_res.scalars().all())

    async def persist_xmi_import(
        self,
        board: Board,
        project_id: str,
        package_id: str,
        parsed: Dict[str, Any],
        filename: str,
    ) -> Dict[str, Any]:
        """
        Persiste los datos parseados de XMI en la base de datos de manera atómica (sin N+1):
        - Deduplica clases (por external_ref o nombre insensible a mayúsculas/minúsculas).
        - Gestiona paquetes y crea subpaquetes jerárquicos según sea necesario.
        - Sincroniza y fusiona atributos en lote.
        - Sincroniza geometría visual en BoardElement en lote.
        - Deduplica y persiste asociaciones UML en lote.
        - Registra evento en BoardHistory y genera snapshot inmutable.
        - En caso de fallo, ejecuta rollback total para preservar consistencia relacional.
        """
        board_id = board.id

        try:
            existing_classes = await self.get_project_classes(project_id)
            existing_by_ext_ref = {c.external_ref: c for c in existing_classes if c.external_ref}
            existing_by_name = {c.name.lower(): c for c in existing_classes}

            # Batch 1: Pre-cargar atributos existentes para eliminar N+1 en clases previas
            existing_cids = [c.id for c in existing_classes]
            existing_attrs_by_cid: Dict[str, Dict[str, Attribute]] = {}
            if existing_cids:
                attrs_stmt = select(Attribute).where(Attribute.class_id.in_(existing_cids))
                attrs_res = await self.db.execute(attrs_stmt)
                for a in attrs_res.scalars().all():
                    existing_attrs_by_cid.setdefault(a.class_id, {})[a.name.lower()] = a

            # Batch 2: Pre-cargar BoardElements existentes del tablero para eliminar N+1
            bes_stmt = select(BoardElement).where(BoardElement.board_id == board_id)
            bes_res = await self.db.execute(bes_stmt)
            existing_bes_by_cid = {be.class_id: be for be in bes_res.scalars().all()}

            created_classes: List[str] = []
            updated_classes: List[str] = []
            class_id_map: Dict[str, str] = {}

            raw_pkgs = await self.get_project_packages(project_id)
            project_packages_by_name = {p.name.lower(): p for p in raw_pkgs}

            for cls in parsed.get("classes", []):
                c_name = cls.get("name")
                if not c_name:
                    continue

                ext_ref = cls.get("external_ref")
                c_type_str = cls.get("element_type", "class").lower()
                c_type = ClassifierType.interface if c_type_str == "interface" else ClassifierType.class_
                is_abs = cls.get("is_abstract", False)

                class_elem = None
                if ext_ref and ext_ref in existing_by_ext_ref:
                    class_elem = existing_by_ext_ref[ext_ref]
                elif c_name.lower() in existing_by_name:
                    class_elem = existing_by_name[c_name.lower()]

                if class_elem:
                    class_elem.name = c_name
                    class_elem.element_type = c_type
                    class_elem.is_abstract = is_abs
                    if ext_ref and not class_elem.external_ref:
                        class_elem.external_ref = ext_ref
                    updated_classes.append(c_name)
                else:
                    target_pkg_id = package_id
                    if cls.get("package_name"):
                        p_name = cls.get("package_name")
                        if p_name.lower() in project_packages_by_name:
                            target_pkg_id = project_packages_by_name[p_name.lower()].id
                        else:
                            new_pkg = Package(project_id=project_id, name=p_name)
                            self.db.add(new_pkg)
                            await self.db.flush()
                            project_packages_by_name[p_name.lower()] = new_pkg
                            target_pkg_id = new_pkg.id

                    class_elem = ClassElement(
                        package_id=target_pkg_id,
                        name=c_name,
                        element_type=c_type,
                        is_abstract=is_abs,
                        external_ref=ext_ref,
                        source=ClassSource.archi_import,
                    )
                    self.db.add(class_elem)
                    await self.db.flush()
                    created_classes.append(c_name)

                class_id_map[cls["id"]] = class_elem.id
                class_id_map[c_name] = class_elem.id

                # Atributos: fusionar/actualizar sin N+1
                existing_attrs = existing_attrs_by_cid.get(class_elem.id, {})

                for idx, attr in enumerate(cls.get("attributes", [])):
                    a_name = attr.get("name", "attr")
                    vis_str = attr.get("visibility", "public").lower()
                    vis = VisibilityEnum.public
                    if vis_str in ["private", "-"]:
                        vis = VisibilityEnum.private
                    elif vis_str in ["protected", "#"]:
                        vis = VisibilityEnum.protected
                    elif vis_str in ["package", "~"]:
                        vis = VisibilityEnum.package

                    a_dtype = attr.get("data_type", "VARCHAR")
                    a_pk = attr.get("is_pkey", False)

                    if a_name.lower() in existing_attrs:
                        existing_attr = existing_attrs[a_name.lower()]
                        existing_attr.data_type = a_dtype
                        existing_attr.visibility = vis
                        existing_attr.is_pkey = a_pk
                        existing_attr.order_index = idx
                    else:
                        new_attr = Attribute(
                            class_id=class_elem.id,
                            name=a_name,
                            data_type=a_dtype,
                            visibility=vis,
                            is_pkey=a_pk,
                            order_index=idx,
                        )
                        self.db.add(new_attr)
                        existing_attrs[a_name.lower()] = new_attr

                # Geometría visual en BoardElement sin N+1
                pos = cls.get("position", {"x": 100.0, "y": 100.0})
                be = existing_bes_by_cid.get(class_elem.id)

                if be:
                    be.x = pos.get("x", be.x)
                    be.y = pos.get("y", be.y)
                    be.width = pos.get("w", be.width or 220.0)
                    be.height = pos.get("h", be.height or 160.0)
                else:
                    be = BoardElement(
                        board_id=board_id,
                        class_id=class_elem.id,
                        x=pos.get("x", 100.0),
                        y=pos.get("y", 100.0),
                        width=pos.get("w", 220.0),
                        height=pos.get("h", 160.0),
                    )
                    self.db.add(be)
                    existing_bes_by_cid[class_elem.id] = be

            # Batch 3: Pre-cargar asociaciones existentes de las clases del modelo
            all_resolved_cids = list(set(class_id_map.values()))
            existing_assocs_map: Dict[Tuple[str, str, AssociationType], Association] = {}
            if all_resolved_cids:
                assocs_stmt = select(Association).where(
                    Association.source_class_id.in_(all_resolved_cids)
                )
                assocs_res = await self.db.execute(assocs_stmt)
                for a in assocs_res.scalars().all():
                    existing_assocs_map[(a.source_class_id, a.target_class_id, a.type)] = a

            imported_associations = 0
            for assoc in parsed.get("associations", []):
                src_raw = assoc.get("sourceId")
                tgt_raw = assoc.get("targetId")
                src_id = class_id_map.get(src_raw)
                tgt_id = class_id_map.get(tgt_raw)

                if not src_id or not tgt_id:
                    continue

                rel_type_str = assoc.get("type", "association").lower()
                assoc_type = AssociationType.association
                if "generalization" in rel_type_str:
                    assoc_type = AssociationType.generalization
                elif "realization" in rel_type_str:
                    assoc_type = AssociationType.realization
                elif "aggregation" in rel_type_str:
                    assoc_type = AssociationType.aggregation
                elif "composition" in rel_type_str:
                    assoc_type = AssociationType.composition

                assoc_key = (src_id, tgt_id, assoc_type)
                assoc_elem = existing_assocs_map.get(assoc_key)

                if assoc_elem:
                    assoc_elem.name = assoc.get("name") or assoc_elem.name
                    assoc_elem.source_role = assoc.get("source_role") or assoc_elem.source_role
                    assoc_elem.target_role = assoc.get("target_role") or assoc_elem.target_role
                    assoc_elem.source_multiplicity = assoc.get("source_multiplicity") or assoc_elem.source_multiplicity
                    assoc_elem.target_multiplicity = assoc.get("target_multiplicity") or assoc_elem.target_multiplicity
                else:
                    assoc_elem = Association(
                        source_class_id=src_id,
                        target_class_id=tgt_id,
                        type=assoc_type,
                        name=assoc.get("name"),
                        source_role=assoc.get("source_role"),
                        target_role=assoc.get("target_role"),
                        source_multiplicity=assoc.get("source_multiplicity"),
                        target_multiplicity=assoc.get("target_multiplicity"),
                    )
                    self.db.add(assoc_elem)
                    existing_assocs_map[assoc_key] = assoc_elem

                if assoc.get("association_class_id"):
                    ac_raw = assoc.get("association_class_id")
                    ac_id = class_id_map.get(ac_raw)
                    if ac_id and assoc_elem:
                        await self.db.flush()
                        acl_stmt = select(AssociationClassLink).where(
                            AssociationClassLink.association_id == assoc_elem.id,
                            AssociationClassLink.class_id == ac_id,
                        )
                        acl_res = await self.db.execute(acl_stmt)
                        if not acl_res.scalar_one_or_none():
                            self.db.add(AssociationClassLink(
                                id=str(uuid.uuid4()),
                                association_id=assoc_elem.id,
                                class_id=ac_id,
                            ))

                imported_associations += 1

            new_version = (board.diagram_version or 0) + 1
            board.diagram_version = new_version

            history_entry = BoardHistory(
                id=str(uuid.uuid4()),
                board_id=board_id,
                command_id=f"cmd-import-xmi-{uuid.uuid4()}",
                command_type="IMPORT_XMI",
                payload={
                    "filename": filename,
                    "created_count": len(created_classes),
                    "updated_count": len(updated_classes),
                    "associations_count": imported_associations,
                },
                actor_id=None,
                actor_type=ActorTypeEnum.user,
                model_version=new_version,
            )
            self.db.add(history_entry)
            await self.db.flush()

            normalized_state = await get_normalized_board_state(self.db, board_id)
            if normalized_state:
                snap = BoardSnapshot(
                    id=str(uuid.uuid4()),
                    board_id=board_id,
                    version=new_version,
                    snapshot=normalized_state,
                )
                self.db.add(snap)

            await self.db.commit()

            return {
                "created_classes": created_classes,
                "updated_classes": updated_classes,
                "imported_associations": imported_associations,
                "normalized_state": normalized_state,
            }
        except Exception:
            await self.db.rollback()
            raise
