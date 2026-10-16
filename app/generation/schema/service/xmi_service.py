"""
Motor de Exportación e Importación de XMI 2.1 compatible con Enterprise Architect (Sparx EA) y OMG UML 2.x.
"""
import hashlib
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# ─── Mapeos de Tipos y Visibilidad ───────────────────────────────────────────

VISIBILITY_MAP_TO_UML = {
    "public": "public",
    "+": "public",
    "private": "private",
    "-": "private",
    "protected": "protected",
    "#": "protected",
    "package": "package",
    "~": "package",
}

VISIBILITY_MAP_FROM_UML = {
    "public": "public",
    "private": "private",
    "protected": "protected",
    "package": "package",
}


def _make_ea_id(val: str) -> str:
    """Genera un identificador compatible con Enterprise Architect (EAID_...)."""
    clean = val.replace("-", "_")
    if clean.startswith("EAID_"):
        return clean
    return f"EAID_{clean}"


def _make_ea_pkg_id(val: str) -> str:
    """Genera un identificador de paquete compatible con Enterprise Architect (EAPK_...)."""
    clean = val.replace("-", "_")
    if clean.startswith("EAPK_"):
        return clean
    return f"EAPK_{clean}"


def _make_duid(val: str) -> str:
    """Genera un DUID hexadecimal de 8 caracteres determinista y único para elementos gráficos de EA."""
    return hashlib.sha256(val.encode("utf-8")).hexdigest()[:8].upper()


def _get_relation_category(rel_type: Optional[str]) -> str:
    """Clasifica el tipo de relación según el estándar UML de dgram."""
    if not rel_type:
        return "Association"
    t = str(rel_type).lower().strip()
    if t.startswith("generalization") or t.startswith("inheritance"):
        return "Generalization"
    if t.startswith("aggregation"):
        return "Aggregation"
    if t.startswith("composition"):
        return "Composition"
    if t.startswith("dependency") or t.startswith("usage"):
        return "Dependency"
    if t.startswith("realization") or t.startswith("implementation"):
        return "Realization"
    return "Association"


class XmiExporter:
    """
    Serializador a formato XMI 2.1 con extensiones visuales de Enterprise Architect.
    """

    def _append_multiplicity(self, parent: ET.Element, mult_str: str, id_prefix: str) -> None:
        if not mult_str:
            return
        mult = str(mult_str).strip()
        if ".." in mult:
            parts = mult.split("..", 1)
            lower, upper = parts[0].strip(), parts[1].strip()
        else:
            lower = mult
            upper = mult

        if lower:
            ET.SubElement(
                parent,
                "lowerValue",
                {
                    "xmi:type": "uml:LiteralInteger",
                    "xmi:id": f"{id_prefix}_lower",
                    "value": lower,
                },
            )
        if upper:
            u_type = "uml:LiteralUnlimitedNatural" if upper == "*" else "uml:LiteralInteger"
            ET.SubElement(
                parent,
                "upperValue",
                {
                    "xmi:type": u_type,
                    "xmi:id": f"{id_prefix}_upper",
                    "value": upper,
                },
            )

    def export_board(
        self,
        project_name: str,
        board_name: str,
        classes: List[Dict[str, Any]],
        associations: List[Dict[str, Any]],
        board_elements: Optional[Dict[str, Dict[str, float]]] = None,
        packages: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Exporta el modelo y la vista del diagrama a XML XMI 2.1 con soporte de jerarquía de paquetes.
        """
        board_elements = board_elements or {}
        packages = packages or []
        model_id = _make_ea_id(str(uuid.uuid4()))
        root_pkg_id = _make_ea_pkg_id(str(uuid.uuid4()))
        diag_id = _make_ea_id(str(uuid.uuid4()))

        # Root <xmi:XMI>
        root = ET.Element(
            "xmi:XMI",
            {
                "xmi:version": "2.1",
                "xmlns:uml": "http://schema.omg.org/spec/UML/2.1",
                "xmlns:xmi": "http://schema.omg.org/spec/XMI/2.1",
            },
        )

        # <xmi:Documentation> (Enterprise Architect requiere exporter="Enterprise Architect" para procesar su bloque Extension)
        doc = ET.SubElement(root, "xmi:Documentation")
        doc.set("exporter", "Enterprise Architect")
        doc.set("exporterVersion", "6.5")

        # <uml:Model>
        model = ET.SubElement(
            root,
            "uml:Model",
            {
                "xmi:type": "uml:Model",
                "name": "EA_Model",
                "visibility": "public",
            },
        )

        # Manejo consistente de paquetes compatible con Enterprise Architect:
        # En EA XMI 2.1 el paquete raíz del modelo lleva prefijo EAPK_ y se nombra según el board/proyecto.
        # Las clases sin paquete específico residen directamente aquí.
        root_pkg_name = "Logical View"
        root_pkg = ET.SubElement(
            model,
            "packagedElement",
            {
                "xmi:type": "uml:Package",
                "name": root_pkg_name,
                "xmi:id": root_pkg_id,
                "visibility": "public",
            },
        )
        pkg_elem_map: Dict[str, ET.Element] = {
            "default": root_pkg,
            "Default": root_pkg,
            "logical view": root_pkg,
            "Logical View": root_pkg,
        }
        pkg_id_map: Dict[str, str] = {
            "default": root_pkg_id,
            "Default": root_pkg_id,
            "logical view": root_pkg_id,
            "Logical View": root_pkg_id,
        }
        if board_name:
            pkg_elem_map[board_name] = root_pkg
            pkg_id_map[board_name] = root_pkg_id
        if project_name:
            pkg_elem_map[project_name] = root_pkg
            pkg_id_map[project_name] = root_pkg_id

        created_packages: List[Dict[str, str]] = [{"id": root_pkg_id, "name": root_pkg_name}]

        if packages:
            for p in packages:
                p_id = p.get("id") or str(uuid.uuid4())
                p_name = p.get("name") or "Package"
                if p_name.lower() in ("default", "logical view") or p_name == root_pkg_name:
                    pkg_elem_map[p_id] = root_pkg
                    pkg_elem_map[p_name] = root_pkg
                    pkg_id_map[p_id] = root_pkg_id
                    pkg_id_map[p_name] = root_pkg_id
                    continue
                ea_pid = _make_ea_pkg_id(p_id)
                pkg_elem = ET.SubElement(
                    model,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Package",
                        "name": p_name,
                        "xmi:id": ea_pid,
                        "visibility": "public",
                    },
                )
                pkg_elem_map[p_id] = pkg_elem
                pkg_elem_map[p_name] = pkg_elem
                pkg_id_map[p_id] = ea_pid
                pkg_id_map[p_name] = ea_pid
                created_packages.append({"id": ea_pid, "name": p_name})

        class_id_map: Dict[str, str] = {}
        class_node_map: Dict[str, ET.Element] = {}
        class_duid_map: Dict[str, str] = {}
        class_pkg_map: Dict[str, ET.Element] = {}
        class_parent_pkg_id: Dict[str, str] = {}

        # Normalización matemática de coordenadas espaciales
        # Si hay coordenadas negativas o desfasadas, se traslada todo el diagrama rígidamente
        # para que Left >= 50 y Top >= 50, preservando al 100% las distancias relativas.
        PADDING = 50.0
        raw_coords: Dict[str, Dict[str, float]] = {}
        for cls in classes:
            c_id = cls.get("id") or ""
            pos = board_elements.get(c_id) or cls.get("position") or {}
            raw_coords[c_id] = {
                "x": float(pos.get("x", 100.0)),
                "y": float(pos.get("y", 100.0)),
                "w": float(pos.get("w", 220.0)),
                "h": float(pos.get("h", 160.0)),
            }

        min_x = min((c["x"] for c in raw_coords.values()), default=PADDING)
        min_y = min((c["y"] for c in raw_coords.values()), default=PADDING)

        shift_x = (PADDING - min_x) if min_x < PADDING else 0.0
        shift_y = (PADDING - min_y) if min_y < PADDING else 0.0

        class_name_map: Dict[str, str] = {}
        # Mapeos bidireccionales para clases de asociación (nType="17" y conID/associationclass)
        assoc_to_ac_map: Dict[str, str] = {}
        ac_to_assoc_map: Dict[str, str] = {}
        for a in associations:
            ac_id = a.get("association_class_id")
            if ac_id:
                a_id = a.get("id") or str(uuid.uuid4())
                assoc_to_ac_map[a_id] = ac_id
                ac_to_assoc_map[ac_id] = a_id
        assoc_class_ids = set(assoc_to_ac_map.values())

        # 1. Clases e Interfaces
        for cls in classes:
            c_id = cls.get("id") or str(uuid.uuid4())
            c_name = cls.get("name", "Class")
            ext_ref = cls.get("external_ref")
            ea_class_id = ext_ref if ext_ref else _make_ea_id(c_id)
            class_id_map[c_id] = ea_class_id
            class_name_map[ea_class_id] = c_name
            class_name_map[c_id] = c_name
            if cls.get("name"):
                class_id_map[cls["name"]] = ea_class_id
                class_name_map[cls["name"]] = c_name

            duid = _make_duid(ea_class_id)
            class_duid_map[ea_class_id] = duid
            class_duid_map[c_id] = duid
            if cls.get("name"):
                class_duid_map[cls["name"]] = duid

            raw_elem_type = str(cls.get("element_type") or cls.get("stereotype") or "").lower()
            is_assoc_class = c_id in assoc_class_ids or raw_elem_type in ("association_class", "associationclass")
            if raw_elem_type in ("enumeration", "enum"):
                uml_type = "uml:Enumeration"
            elif raw_elem_type == "interface":
                uml_type = "uml:Interface"
            elif raw_elem_type in ("datatype", "data_type"):
                uml_type = "uml:DataType"
            else:
                uml_type = "uml:Class"

            # Determinar paquete destino (específico o root_pkg)
            cls_pkg_id = cls.get("package_id") or cls.get("package_name")
            target_pkg = pkg_elem_map.get(cls_pkg_id, root_pkg)
            target_pkg_id = pkg_id_map.get(cls_pkg_id, root_pkg_id)
            class_parent_pkg_id[ea_class_id] = target_pkg_id
            class_pkg_map[ea_class_id] = target_pkg
            class_pkg_map[c_id] = target_pkg
            if cls.get("name"):
                class_pkg_map[cls["name"]] = target_pkg

            elem_attrs = {
                "xmi:type": uml_type,
                "xmi:id": ea_class_id,
                "name": cls.get("name", "Class1"),
            }
            if is_assoc_class:
                elem_attrs["stereotype"] = "association class"

            cls_elem = ET.SubElement(
                target_pkg,
                "packagedElement",
                elem_attrs,
            )
            class_node_map[ea_class_id] = cls_elem
            class_node_map[c_id] = cls_elem
            if cls.get("name"):
                class_node_map[cls["name"]] = cls_elem

            if cls.get("is_abstract"):
                cls_elem.set("isAbstract", "true")

            # Atributos / Propiedades / Literales
            for attr in cls.get("attributes", []):
                attr_id = _make_ea_id(attr.get("id") or str(uuid.uuid4()))
                attr["_ea_attr_id"] = attr_id
                vis = VISIBILITY_MAP_TO_UML.get(str(attr.get("visibility", "public")).lower(), "public")

                if uml_type == "uml:Enumeration":
                    ET.SubElement(
                        cls_elem,
                        "ownedLiteral",
                        {
                            "xmi:type": "uml:EnumerationLiteral",
                            "xmi:id": attr_id,
                            "name": attr.get("name", "VAL"),
                        },
                    )
                elif uml_type == "uml:Interface" or "(" in str(attr.get("name", "")):
                    op = ET.SubElement(
                        cls_elem,
                        "ownedOperation",
                        {
                            "xmi:type": "uml:Operation",
                            "xmi:id": attr_id,
                            "name": attr.get("name", "operation"),
                            "visibility": vis,
                        },
                    )
                    dtype = attr.get("data_type") or attr.get("type") or "void"
                    if dtype and dtype.lower() != "void":
                        ret_param = ET.SubElement(
                            op,
                            "ownedParameter",
                            {
                                "xmi:type": "uml:Parameter",
                                "xmi:id": f"{attr_id}_ret",
                                "direction": "return",
                            },
                        )
                        ET.SubElement(
                            ret_param,
                            "type",
                            {
                                "xmi:type": "uml:PrimitiveType",
                                "href": f"http://schema.omg.org/spec/UML/2.1/uml.xml#{dtype}",
                            },
                        )
                else:
                    prop = ET.SubElement(
                        cls_elem,
                        "ownedAttribute",
                        {
                            "xmi:type": "uml:Property",
                            "xmi:id": attr_id,
                            "name": attr.get("name", "attr"),
                            "visibility": vis,
                            "isOrdered": "false",
                            "isUnique": "true",
                        },
                    )
                    if attr.get("is_pkey"):
                        prop.set("isID", "true")
                    if attr.get("is_derived"):
                        prop.set("isDerived", "true")
                    is_pk = bool(attr.get("is_pkey"))
                    is_fk = bool(attr.get("is_fkey"))
                    if is_pk and is_fk:
                        prop.set("stereotype", "PK, FK")
                    elif is_pk:
                        prop.set("stereotype", "PK")
                    elif is_fk:
                        prop.set("stereotype", "FK")

                    # Tipo primitivo o personalizado
                    dtype = attr.get("data_type") or attr.get("type") or "String"
                    ET.SubElement(
                        prop,
                        "type",
                        {
                            "xmi:type": "uml:PrimitiveType",
                            "href": f"http://schema.omg.org/spec/UML/2.1/uml.xml#{dtype}",
                        },
                    )
                    if attr.get("default_value") is not None and str(attr.get("default_value")).strip() != "":
                        dval = str(attr.get("default_value")).strip()
                        ET.SubElement(
                            prop,
                            "defaultValue",
                            {
                                "xmi:type": "uml:LiteralString",
                                "xmi:id": f"{attr_id}_default",
                                "value": dval,
                            },
                        )

        # 2. Asociaciones y Generalizaciones
        associations_for_diagram: List[Dict[str, Any]] = []
        for assoc in associations:
            assoc_id = _make_ea_id(assoc.get("id") or str(uuid.uuid4()))
            src_id = assoc.get("sourceId") or assoc.get("source_class_id") or ""
            tgt_id = assoc.get("targetId") or assoc.get("target_class_id") or ""
            rel_type = str(assoc.get("type", "Association")).strip()
            rel_type_lower = rel_type.lower()

            ea_src = class_id_map.get(src_id, _make_ea_id(src_id))
            ea_tgt = class_id_map.get(tgt_id, _make_ea_id(tgt_id))

            src_role = assoc.get("source_role") or assoc.get("sourceRole")
            tgt_role = assoc.get("target_role") or assoc.get("targetRole")
            src_mult = assoc.get("source_multiplicity") or assoc.get("sourceMultiplicity")
            tgt_mult = assoc.get("target_multiplicity") or assoc.get("targetMultiplicity")

            ac_id = assoc.get("association_class_id")
            ea_ac = class_id_map.get(ac_id, _make_ea_id(ac_id)) if ac_id else None

            # En EA y en el canvas de dgram, solo la relación Asociación (incluyendo Clase de Asociación)
            # debe mostrar y exportar cardinalidades; las demás (Agregación, Composición, etc.) no deben llevar cardinalidad.
            cat = _get_relation_category(rel_type)
            is_assoc_category = (cat == "Association") or bool(ac_id)
            if not is_assoc_category:
                src_mult = None
                tgt_mult = None

            associations_for_diagram.append({
                "id": assoc_id,
                "ea_src": ea_src,
                "ea_tgt": ea_tgt,
                "rel_type": rel_type,
                "src_name": class_name_map.get(ea_src, ""),
                "tgt_name": class_name_map.get(ea_tgt, ""),
                "src_role": src_role,
                "tgt_role": tgt_role,
                "src_mult": src_mult,
                "tgt_mult": tgt_mult,
                "association_class_id": ea_ac,
            })

            is_gen = rel_type_lower in ["generalization", "inheritance"]
            is_real = rel_type_lower in ["realization", "implementation"]
            is_dep = rel_type_lower in ["dependency", "usage"]

            if is_gen:
                # Find the source class element to append <generalization> across any package
                src_node = class_node_map.get(ea_src)
                if src_node is None:
                    src_node = class_node_map.get(src_id)
                if src_node is not None:
                    ET.SubElement(
                        src_node,
                        "generalization",
                        {
                            "xmi:type": "uml:Generalization",
                            "xmi:id": assoc_id,
                            "general": ea_tgt,
                        },
                    )
            elif is_real:
                ET.SubElement(
                    root_pkg,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Realization",
                        "xmi:id": assoc_id,
                        "supplier": ea_tgt,
                        "client": ea_src,
                    },
                )
            elif is_dep:
                ET.SubElement(
                    root_pkg,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Dependency",
                        "xmi:id": assoc_id,
                        "supplier": ea_tgt,
                        "client": ea_src,
                        "name": assoc.get("name") or "",
                    },
                )
            else:
                # Standard Association / Aggregation / Composition
                assoc_elem = ET.SubElement(
                    root_pkg,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Association",
                        "xmi:id": assoc_id,
                        "name": assoc.get("name") or "",
                    },
                )
                # Ends
                ET.SubElement(
                    assoc_elem,
                    "memberEnd",
                    {"xmi:idref": f"{assoc_id}_src"},
                )
                ET.SubElement(
                    assoc_elem,
                    "memberEnd",
                    {"xmi:idref": f"{assoc_id}_tgt"},
                )

                # Owned ends
                oe1 = ET.SubElement(
                    assoc_elem,
                    "ownedEnd",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": f"{assoc_id}_src",
                        "type": ea_src,
                        "association": assoc_id,
                    },
                )
                if rel_type_lower == "aggregation":
                    oe1.set("aggregation", "shared")
                elif rel_type_lower == "composition":
                    oe1.set("aggregation", "composite")

                if src_role:
                    oe1.set("name", src_role)
                if src_mult:
                    self._append_multiplicity(oe1, src_mult, f"{assoc_id}_src")

                oe2 = ET.SubElement(
                    assoc_elem,
                    "ownedEnd",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": f"{assoc_id}_tgt",
                        "type": ea_tgt,
                        "association": assoc_id,
                    },
                )
                if tgt_role:
                    oe2.set("name", tgt_role)
                if tgt_mult:
                    self._append_multiplicity(oe2, tgt_mult, f"{assoc_id}_tgt")

        # 3. <xmi:Extension extender="Enterprise Architect"> (Metadata & Diagram Layout)
        ext = ET.SubElement(
            root,
            "xmi:Extension",
            {
                "extender": "Enterprise Architect",
                "extenderID": "6.5",
            },
        )

        # 3.1 <elements> block (Required by EA 17 to map packages & classifier metadata)
        elements_ext_node = ET.SubElement(ext, "elements")

        # Registrar clasificadores (Clases, Interfaces, etc.) en <elements>
        for cls in classes:
            c_id = cls.get("id") or ""
            ea_id = class_id_map.get(c_id, _make_ea_id(c_id))
            c_name = cls.get("name", "Class1")
            raw_t = str(cls.get("element_type") or cls.get("type") or cls.get("stereotype") or "").lower()
            is_ac = c_id in assoc_class_ids or raw_t in ("association_class", "associationclass")
            if raw_t in ("interface",) or cls.get("is_interface"):
                s_type = "Interface"
                u_type = "uml:Interface"
            elif raw_t in ("enumeration", "enum") or cls.get("is_enum"):
                s_type = "Enumeration"
                u_type = "uml:Enumeration"
            elif raw_t in ("datatype", "data_type"):
                s_type = "DataType"
                u_type = "uml:DataType"
            else:
                s_type = "Class"
                u_type = "uml:Class"

            parent_pkg_ea_id = class_parent_pkg_id.get(ea_id, root_pkg_id)
            elem_cls = ET.SubElement(
                elements_ext_node,
                "element",
                {
                    "xmi:idref": ea_id,
                    "xmi:type": u_type,
                    "name": c_name,
                    "scope": "public",
                },
            )
            ET.SubElement(
                elem_cls,
                "model",
                {
                    "package": parent_pkg_ea_id,
                    "tpos": "0",
                    "ea_eleType": "element",
                },
            )
            props_elem = ET.SubElement(
                elem_cls,
                "properties",
                {
                    "isSpecification": "false",
                    "sType": s_type,
                    "nType": "17" if is_ac else "0",
                    "scope": "public",
                },
            )
            if is_ac:
                props_elem.set("stereotype", "association class")
                assoc_conn_id = ac_to_assoc_map.get(c_id) or ac_to_assoc_map.get(ea_id)
                if assoc_conn_id:
                    ea_conn_id = _make_ea_id(assoc_conn_id)
                    props_elem.set("conID", ea_conn_id)
                    ET.SubElement(elem_cls, "extendedProperties", {"conID": ea_conn_id})
                    tags_elem = ET.SubElement(elem_cls, "tags")
                    ET.SubElement(tags_elem, "tag", {"name": "conID", "value": ea_conn_id})
                    ET.SubElement(tags_elem, "tag", {"name": "ea_ntype", "value": "17"})
            elif s_type == "DataType":
                props_elem.set("stereotype", "dataType")
            if cls.get("is_abstract"):
                props_elem.set("isAbstract", "true")

            ET.SubElement(
                elem_cls,
                "project",
                {
                    "author": "dgram",
                    "version": "1.0",
                    "phase": "1.0",
                    "complexity": "1",
                    "status": "Proposed",
                },
            )

            # Atributos en la extensión de EA (preserva orden con Pos, inicial, derivados y PK/FK)
            cls_attrs = cls.get("attributes", [])
            if cls_attrs and s_type not in ("Enumeration",):
                attrs_node = ET.SubElement(elem_cls, "attributes")
                for a_idx, attr in enumerate(cls_attrs):
                    attr_id = attr.get("_ea_attr_id") or _make_ea_id(attr.get("id") or str(uuid.uuid4()))
                    a_elem = ET.SubElement(
                        attrs_node,
                        "attribute",
                        {
                            "xmi:idref": attr_id,
                            "name": attr.get("name", "attr"),
                            "scope": "Public",
                        },
                    )
                    ET.SubElement(
                        a_elem,
                        "model",
                        {
                            "ea_localid": str(a_idx + 1),
                            "position": str(a_idx),
                        },
                    )
                    dtype = attr.get("data_type") or attr.get("type") or "String"
                    a_props = {
                        "pos": str(a_idx),
                        "type": dtype,
                    }
                    if attr.get("is_derived"):
                        a_props["derived"] = "1"

                    is_pk = bool(attr.get("is_pkey"))
                    is_fk = bool(attr.get("is_fkey"))
                    if is_pk and is_fk:
                        a_props["stereotype"] = "PK, FK"
                    elif is_pk:
                        a_props["stereotype"] = "PK"
                    elif is_fk:
                        a_props["stereotype"] = "FK"

                    ET.SubElement(a_elem, "properties", a_props)

                    if attr.get("default_value") is not None and str(attr.get("default_value")).strip() != "":
                        dval = str(attr.get("default_value")).strip()
                        ET.SubElement(a_elem, "initial", {"body": dval})

        # 3.2 <connectors> block (Required by EA to map relations in t_connector and t_diagramlinks)
        if associations_for_diagram:
            connectors_node = ET.SubElement(ext, "connectors")
            for assoc_rec in associations_for_diagram:
                conn_elem = ET.SubElement(connectors_node, "connector", {"xmi:idref": assoc_rec["id"]})

                rt = str(assoc_rec.get("rel_type", "")).lower()
                src_agg = "none"
                props_attrs = {"ea_type": "Association", "direction": "Unspecified"}

                ea_ac = assoc_rec.get("association_class_id")
                if ea_ac or rt == "association_class":
                    props_attrs["ea_type"] = "Association"
                    props_attrs["direction"] = "Unspecified"
                    props_attrs["subtype"] = "Class"
                    if ea_ac:
                        props_attrs["class_guid"] = ea_ac
                elif rt in ("generalization", "inheritance"):
                    props_attrs["ea_type"] = "Generalization"
                    props_attrs["direction"] = "Source -> Destination"
                elif rt in ("realization", "implementation"):
                    props_attrs["ea_type"] = "Realisation"
                    props_attrs["direction"] = "Source -> Destination"
                elif rt in ("dependency", "usage"):
                    props_attrs["ea_type"] = "Dependency"
                    props_attrs["direction"] = "Source -> Destination"
                elif rt == "aggregation":
                    src_agg = "shared"
                    props_attrs["ea_type"] = "Aggregation"
                    props_attrs["direction"] = "Source -> Destination"
                elif rt == "composition":
                    src_agg = "composite"
                    props_attrs["ea_type"] = "Aggregation"
                    props_attrs["direction"] = "Source -> Destination"
                    props_attrs["subtype"] = "Strong"
                else:
                    props_attrs["ea_type"] = "Association"
                    props_attrs["direction"] = "Unspecified"

                # source
                src_elem = ET.SubElement(conn_elem, "source", {"xmi:idref": assoc_rec["ea_src"]})
                ET.SubElement(src_elem, "model", {"type": "Class", "name": assoc_rec.get("src_name", "")})
                src_role_attrs = {"visibility": "Public", "targetScope": "instance"}
                if assoc_rec.get("src_role"):
                    src_role_attrs["name"] = assoc_rec["src_role"]
                ET.SubElement(src_elem, "role", src_role_attrs)
                src_type_attrs = {"aggregation": src_agg, "containment": "Unspecified"}
                if assoc_rec.get("src_mult"):
                    src_type_attrs["multiplicity"] = assoc_rec["src_mult"]
                ET.SubElement(src_elem, "type", src_type_attrs)

                # target
                tgt_elem = ET.SubElement(conn_elem, "target", {"xmi:idref": assoc_rec["ea_tgt"]})
                ET.SubElement(tgt_elem, "model", {"type": "Class", "name": assoc_rec.get("tgt_name", "")})
                tgt_role_attrs = {"visibility": "Public", "targetScope": "instance"}
                if assoc_rec.get("tgt_role"):
                    tgt_role_attrs["name"] = assoc_rec["tgt_role"]
                ET.SubElement(tgt_elem, "role", tgt_role_attrs)
                tgt_type_attrs = {"aggregation": "none", "containment": "Unspecified"}
                if assoc_rec.get("tgt_mult"):
                    tgt_type_attrs["multiplicity"] = assoc_rec["tgt_mult"]
                ET.SubElement(tgt_elem, "type", tgt_type_attrs)

                # properties
                ET.SubElement(conn_elem, "properties", props_attrs)

                if ea_ac:
                    ET.SubElement(conn_elem, "extendedProperties", {"associationclass": ea_ac})
                    tags_conn = ET.SubElement(conn_elem, "tags")
                    ET.SubElement(tags_conn, "tag", {"name": "associationclass", "value": ea_ac})
                    ET.SubElement(tags_conn, "tag", {"name": "subtype", "value": "Class"})

        # 3.3 <diagrams> block
        diagrams_node = ET.SubElement(ext, "diagrams")
        diag_node = ET.SubElement(diagrams_node, "diagram", {"xmi:id": diag_id})

        # Asociar explícitamente el diagrama con su paquete contenedor en EA
        ET.SubElement(
            diag_node,
            "model",
            {
                "package": root_pkg_id,
                "localID": "1",
                "owner": root_pkg_id,
            },
        )

        props_node = ET.SubElement(diag_node, "properties")
        props_node.set("name", "Class Diagram")
        props_node.set("type", "Logical")

        ET.SubElement(
            diag_node,
            "project",
            {
                "author": "dgram",
                "version": "1.0",
            },
        )

        # Metadatos de visualización y estilo de EA para registrar t_diagram
        ET.SubElement(
            diag_node,
            "style1",
            {"value": "ShowPrivate=1;ShowProtected=1;ShowPublic=1;HideRelationships=0;Locked=0;Border=1;HighlightForeign=1;PackageContents=1;SequenceNotes=0;ScalePrintImage=0;PPgs.cx=1;PPgs.cy=1;DocSize.cx=826;DocSize.cy=1169;ShowDetails=0;Orientation=P;Zoom=100;ShowTags=0;OpParams=1;VisibleAttributeDetail=0;ShowOpRetType=1;ShowIcons=1;CollabNums=0;HideProps=0;ShowReqs=0;ShowCons=0;PaperSize=9;HideParents=0;UseAlias=0;HideAtts=0;HideOps=0;HideStereo=0;HideElemStereo=0;ShowTests=0;ShowMaint=0;ConnectorNotation=UML 2.1;ExplicitNavigability=0;ShowShape=1;AllDockable=0;AdvancedElementProps=1;AdvancedFeatureProps=1;AdvancedConnectorProps=1;ShowNotes=0;SuppressBrackets=0;SuppConnectorLabels=0;PrintPageHeadFoot=0;ShowAsList=0;HideConnStereotype=0;ShowFQN=0;NoFullScope=0;"},
        )
        ET.SubElement(
            diag_node,
            "style2",
            {"value": "SaveTag=B278AAE8;ExcludeRTF=0;DocAll=0;HideQuals=0;AttPkg=1;ShowTests=0;ShowMaint=0;SuppressFOC=1;MatrixActive=0;SwimlanesActive=1;MatrixLineWidth=1;MatrixLocked=0;TConnectorNotation=UML 2.1;TExplicitNavigability=0;AdvancedElementProps=1;AdvancedFeatureProps=1;AdvancedConnectorProps=1;ProfileData=;MDGDgm=;DefaultLang=Java;STBLDgm=;ShowNotes=0;VisibleAttributeDetail=0;ShowOpRetType=1;SuppressBrackets=0;SuppConnectorLabels=0;PrintPageHeadFoot=0;ShowAsList=0;OverrideLinkedF=0;HideConnStereotype=0;ShowFQN=0;NoFullScope=0;"},
        )
        ET.SubElement(
            diag_node,
            "swimlanes",
            {"value": "locked=false;orientation=0;width=0;inbar=false;names=false;color=-1;bold=false;fcol=0;tcol=-1;ofCol=-1;ufCol=-1;hl=0;ufh=0;hh=0;cls=0;bw=0;hli=0;bro=0;"},
        )
        ET.SubElement(
            diag_node,
            "matrixitems",
            {"value": "locked=false;matrixactive=false;swimlanesactive=true;width=1;"},
        )
        ET.SubElement(diag_node, "extendedProperties")

        elements_node = ET.SubElement(diag_node, "elements")
        for seq_idx, cls in enumerate(classes, start=1):
            c_id = cls.get("id") or ""
            ea_id = class_id_map.get(c_id, _make_ea_id(c_id))
            coords = raw_coords.get(c_id, {"x": 100.0, "y": 100.0, "w": 220.0, "h": 160.0})
            px = coords["x"] + shift_x
            py = coords["y"] + shift_y
            w = coords["w"]
            h = coords["h"]

            # EA geometry format: Left=X;Top=Y;Right=X+W;Bottom=Y+H;
            left = int(round(px))
            top = int(round(py))
            right = int(round(px + w))
            bottom = int(round(py + h))

            geom_str = f"Left={left};Top={top};Right={right};Bottom={bottom};"
            duid = class_duid_map.get(ea_id, _make_duid(ea_id))
            elem_style = f"DUID={duid};"
            if cls.get("is_abstract"):
                elem_style += "AttFont=lfItalic:1;OpFont=lfItalic:1;"

            ET.SubElement(
                elements_node,
                "element",
                {
                    "geometry": geom_str,
                    "subject": ea_id,
                    "seqno": str(seq_idx),
                    "style": elem_style,
                },
            )

        # Representación visual de conectores en el diagrama para Enterprise Architect
        for assoc_record in associations_for_diagram:
            assoc_id = assoc_record["id"]
            ea_src = assoc_record["ea_src"]
            ea_tgt = assoc_record["ea_tgt"]
            src_duid = class_duid_map.get(ea_src, _make_duid(ea_src))
            tgt_duid = class_duid_map.get(ea_tgt, _make_duid(ea_tgt))

            ET.SubElement(
                elements_node,
                "element",
                {
                    "geometry": "SX=0;SY=0;EX=0;EY=0;EDGE=1;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;Path=;",
                    "subject": assoc_id,
                    "style": f"Mode=3;EOID={tgt_duid};SOID={src_duid};Color=-1;LWidth=0;Hidden=0;",
                },
            )

        # Return formatted XML
        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


class XmiImporter:
    """
    Parser robusto para archivos XMI 2.1 / 2.x exportados desde Enterprise Architect u otras herramientas CASE.
    """

    def _parse_multiplicity(self, end_elem: ET.Element) -> Optional[str]:
        low = end_elem.find(".//lowerValue")
        up = end_elem.find(".//upperValue")
        low_val = low.attrib.get("value") if low is not None else None
        up_val = up.attrib.get("value") if up is not None else None

        if low_val is None and up_val is None:
            low_val = end_elem.attrib.get("lower")
            up_val = end_elem.attrib.get("upper")

        def _norm(v: Any) -> Optional[str]:
            if v is None:
                return None
            s = str(v).strip()
            return "*" if s in ["-1", "*"] else s

        low_str = _norm(low_val)
        up_str = _norm(up_val)

        if low_str is not None and up_str is not None:
            if low_str == up_str:
                return low_str
            return f"{low_str}..{up_str}"
        elif up_str is not None:
            return up_str
        elif low_str is not None:
            return low_str
        return None

    def _parse_ea_geometry(self, geom: str) -> Optional[Dict[str, float]]:
        """
        Parsea un string de geometría EA para elementos (Left=100;Top=150;Right=320;Bottom=310;).
        Ignora geometrías de conectores (SX=...;SY=...;EDGE=...).
        """
        try:
            parts = [p.strip() for p in geom.split(";") if "=" in p]
            kv = dict(p.split("=", 1) for p in parts)
            if "Left" not in kv or "Top" not in kv:
                return None
            left = float(kv.get("Left", 100))
            top = float(kv.get("Top", 100))
            right = float(kv.get("Right", left + 220))
            bottom = float(kv.get("Bottom", top + 160))
            return {
                "x": left,
                "y": top,
                "w": max(right - left, 180.0),
                "h": max(bottom - top, 120.0),
            }
        except Exception:
            return None

    def _resolve_table_overlaps(self, classes: List[Dict[str, Any]], min_gap: float = 50.0) -> None:
        """
        Ajusta las posiciones verticales de las tablas para evitar que se solapen debido
        a la altura real requerida por los atributos en el frontend.
        """
        if not classes or len(classes) < 2:
            return

        # Estimar altura y ancho real para cada clase según cantidad de atributos
        for c in classes:
            attrs_count = len(c.get("attributes", []))
            est_h = max(130.0, 70.0 + attrs_count * 28.0)
            c["position"]["w"] = max(220.0, float(c["position"].get("w", 220.0)))
            c["position"]["h"] = max(est_h, float(c["position"].get("h", 120.0)))

        # Ordenar por coordenada Y
        classes.sort(key=lambda item: (item["position"]["y"], item["position"]["x"]))

        # Realizar pases de resolución de colisiones
        for _ in range(10):
            shifted = False
            for i in range(len(classes)):
                box_a = classes[i]["position"]
                for j in range(i + 1, len(classes)):
                    box_b = classes[j]["position"]

                    # Comprobar solapamiento horizontal
                    x_overlap = (box_a["x"] < box_b["x"] + box_b["w"]) and (box_a["x"] + box_a["w"] > box_b["x"])
                    if x_overlap:
                        # Si colisionan verticalmente o están demasiado cerca
                        min_y = box_a["y"] + box_a["h"] + min_gap
                        if box_b["y"] < min_y:
                            box_b["y"] = min_y
                            shifted = True
            if not shifted:
                break

    def parse(self, xml_content: str) -> Dict[str, Any]:
        """
        Parsea el contenido XML y retorna la estructura del modelo, clases, atributos, relaciones y posiciones visuales.
        """
        if xml_content is None:
            raise ValueError("El contenido XML no puede ser nulo.")

        if isinstance(xml_content, bytes):
            if len(xml_content) > 10 * 1024 * 1024:
                raise ValueError("El archivo XML excede el tamaño máximo permitido de 10 MB.")
            xml_content = xml_content.decode("utf-8", errors="replace")
        elif len(xml_content.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("El archivo XML excede el tamaño máximo permitido de 10 MB.")

        upper_xml = xml_content.upper()
        if "<!ENTITY" in upper_xml or "<!DOCTYPE" in upper_xml:
            if "SYSTEM" in upper_xml or "PUBLIC" in upper_xml:
                raise ValueError("Declaraciones DTD o entidades externas no están permitidas por seguridad.")

        try:
            root = ET.fromstring(xml_content)
        except Exception as e:
            raise ValueError(f"Estructura XML inválida o corrupta: {e}")

        # Namespaces handling: search regardless of prefix
        classes: List[Dict[str, Any]] = []
        associations: List[Dict[str, Any]] = []
        positions: Dict[str, Dict[str, float]] = {}
        packages: List[Dict[str, Any]] = []
        pkg_id_set = set()
        seen_assoc_ids: Set[str] = set()

        # Build parent map for hierarchical package detection
        parent_map = {c: p for p in root.iter() for c in p}

        # 1. Parse EA Geometry and Connectors extensions if present
        ea_connectors: Dict[str, Dict[str, Any]] = {}
        ea_assoc_class_links: Dict[str, str] = {}
        for elem in root.iter():
            if elem.tag.endswith("element") and "geometry" in elem.attrib:
                subject = elem.attrib.get("subject", "")
                geom = elem.attrib.get("geometry", "")
                parsed_geo = self._parse_ea_geometry(geom)
                if subject and parsed_geo:
                    positions[subject] = parsed_geo
            elif elem.tag.endswith("connector"):
                conn_id = elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref") or elem.attrib.get("xmi:idref") or elem.attrib.get("id") or ""
                if not conn_id:
                    continue
                source = elem.find(".//source")
                target = elem.find(".//target")
                props = elem.find(".//properties")

                src_id = (
                    source.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                    or source.attrib.get("xmi:idref")
                    or source.attrib.get("idref")
                    if source is not None else None
                )
                tgt_id = (
                    target.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref")
                    or target.attrib.get("xmi:idref")
                    or target.attrib.get("idref")
                    if target is not None else None
                )
                ea_type = props.attrib.get("ea_type", "Association") if props is not None else "Association"

                src_role = None
                tgt_role = None
                src_mult = None
                tgt_mult = None
                if source is not None:
                    r = source.find(".//role")
                    if r is not None and r.attrib.get("name"):
                        src_role = r.attrib.get("name")
                    m = source.find(".//type")
                    if m is not None and m.attrib.get("multiplicity"):
                        src_mult = m.attrib.get("multiplicity")
                if target is not None:
                    r = target.find(".//role")
                    if r is not None and r.attrib.get("name"):
                        tgt_role = r.attrib.get("name")
                    m = target.find(".//type")
                    if m is not None and m.attrib.get("multiplicity"):
                        tgt_mult = m.attrib.get("multiplicity")

                ea_connectors[conn_id] = {
                    "sourceId": src_id,
                    "targetId": tgt_id,
                    "type": ea_type,
                    "source_role": src_role,
                    "target_role": tgt_role,
                    "source_multiplicity": src_mult,
                    "target_multiplicity": tgt_mult,
                }
            elif elem.tag.endswith("element"):
                el_id = elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}idref") or elem.attrib.get("xmi:idref") or elem.attrib.get("id") or ""
                ext = elem.find(".//extendedProperties")
                if ext is not None and el_id:
                    con_id = ext.attrib.get("conID")
                    if con_id:
                        ea_assoc_class_links[con_id] = el_id

        # 2. Parse Packages, Classes & Interfaces
        for elem in root.iter():
            elem_type = elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type") or elem.attrib.get("xmi:type") or elem.attrib.get("type") or ""
            elem_id = elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or elem.attrib.get("xmi:id") or elem.attrib.get("id") or ""
            name = elem.attrib.get("name")

            if not elem_id:
                continue

            if elem_type == "uml:Package" or elem.tag.endswith("Package"):
                if name and name != "Logical View" and elem_id not in pkg_id_set:
                    pkg_id_set.add(elem_id)
                    packages.append({
                        "id": elem_id,
                        "name": name,
                    })
                continue

            is_assoc_class = elem_type in ["uml:AssociationClass"] or elem.tag.endswith("AssociationClass")
            if (
                elem_type in ["uml:Class", "uml:Interface", "uml:Enumeration", "uml:DataType", "uml:AssociationClass"]
                or elem.tag.endswith("Class")
                or elem.tag.endswith("Interface")
                or elem.tag.endswith("Enumeration")
                or elem.tag.endswith("DataType")
                or elem.tag.endswith("AssociationClass")
            ):
                is_abstract = elem.attrib.get("isAbstract", "false").lower() == "true"
                if "Enumeration" in elem_type or elem.tag.endswith("Enumeration"):
                    classifier = "enumeration"
                elif "Interface" in elem_type or elem.tag.endswith("Interface"):
                    classifier = "interface"
                elif "DataType" in elem_type or elem.tag.endswith("DataType"):
                    classifier = "datatype"
                else:
                    classifier = "class"

                attributes = []
                # Attributes / Properties / Literals
                for child in elem:
                    c_type = child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type") or child.attrib.get("xmi:type") or child.tag
                    if classifier == "enumeration" and (child.tag.endswith("ownedLiteral") or "EnumerationLiteral" in c_type or child.tag.endswith("Literal")):
                        lit_name = child.attrib.get("name")
                        if not lit_name:
                            continue
                        attributes.append({
                            "id": child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or child.attrib.get("xmi:id") or str(uuid.uuid4()),
                            "name": lit_name,
                            "data_type": "String",
                            "visibility": "public",
                            "is_pkey": False,
                            "is_fkey": False,
                            "is_derived": False,
                            "default_value": None,
                        })
                    elif child.tag.endswith("ownedAttribute") or "Property" in c_type:
                        attr_name = child.attrib.get("name")
                        if not attr_name:
                            continue
                        vis = child.attrib.get("visibility", "public")

                        # Data type
                        dtype = "String"
                        type_tag = child.find(".//type")
                        if type_tag is not None:
                            href = type_tag.attrib.get("href", "")
                            if "#" in href:
                                dtype = href.split("#")[-1]
                            elif type_tag.attrib.get("name"):
                                dtype = type_tag.attrib.get("name")

                        is_pk = attr_name.lower() in ["id", "uuid", "pk"] or child.attrib.get("isID", "false").lower() == "true"
                        is_derived = child.attrib.get("isDerived", "false").lower() == "true" or attr_name.startswith("/")
                        if is_derived and attr_name.startswith("/"):
                            attr_name = attr_name[1:].strip()

                        default_val = None
                        d_tag = child.find(".//defaultValue")
                        if d_tag is not None:
                            default_val = d_tag.attrib.get("value")

                        is_fk = "fk" in child.attrib.get("stereotype", "").lower()

                        attributes.append({
                            "id": child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or child.attrib.get("xmi:id") or str(uuid.uuid4()),
                            "name": attr_name,
                            "data_type": dtype,
                            "visibility": VISIBILITY_MAP_FROM_UML.get(vis, "public"),
                            "is_pkey": is_pk,
                            "is_fkey": is_fk,
                            "is_derived": is_derived,
                            "default_value": default_val,
                        })
                    elif child.tag.endswith("ownedOperation") or "Operation" in c_type:
                        op_name = child.attrib.get("name")
                        if not op_name:
                            continue
                        vis = child.attrib.get("visibility", "public")
                        dtype = "void"
                        for param in child.findall(".//ownedParameter"):
                            if param.attrib.get("direction") == "return":
                                type_tag = param.find(".//type")
                                if type_tag is not None:
                                    href = type_tag.attrib.get("href", "")
                                    if "#" in href:
                                        dtype = href.split("#")[-1]
                                    elif type_tag.attrib.get("name"):
                                        dtype = type_tag.attrib.get("name")
                        attributes.append({
                            "id": child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or child.attrib.get("xmi:id") or str(uuid.uuid4()),
                            "name": op_name,
                            "data_type": dtype,
                            "visibility": VISIBILITY_MAP_FROM_UML.get(vis, "public"),
                            "is_pkey": False,
                            "is_fkey": False,
                            "is_derived": False,
                            "default_value": None,
                        })

                # Position from EA extension or default
                pos = positions.get(elem_id, {"x": 100.0 + len(classes) * 40.0, "y": 100.0 + len(classes) * 40.0})

                # Check enclosing package
                curr = parent_map.get(elem)
                pkg_id_for_cls = None
                pkg_name_for_cls = None
                while curr is not None:
                    curr_type = curr.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type") or curr.attrib.get("xmi:type") or curr.attrib.get("type") or ""
                    if curr_type == "uml:Package" or curr.tag.endswith("Package"):
                        curr_name = curr.attrib.get("name", "")
                        curr_id = curr.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or curr.attrib.get("xmi:id") or curr.attrib.get("id") or ""
                        if curr_name != "Logical View" and curr_id:
                            pkg_id_for_cls = curr_id
                            pkg_name_for_cls = curr_name
                            break
                    curr = parent_map.get(curr)

                classes.append({
                    "id": elem_id,
                    "external_ref": elem_id,
                    "name": name,
                    "element_type": classifier,
                    "is_abstract": is_abstract,
                    "attributes": attributes,
                    "position": pos,
                    "package_id": pkg_id_for_cls,
                    "package_name": pkg_name_for_cls,
                })

            # Generalization
            if elem.tag.endswith("generalization") or elem_type == "uml:Generalization":
                src_cls = elem.attrib.get("specific") or elem.attrib.get("client")
                if not src_cls:
                    parent = parent_map.get(elem)
                    if parent is not None:
                        src_cls = parent.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or parent.attrib.get("xmi:id") or parent.attrib.get("id")
                tgt_cls = elem.attrib.get("general") or elem.attrib.get("supplier")
                if src_cls and tgt_cls:
                    associations.append({
                        "id": elem_id,
                        "sourceId": src_cls,
                        "targetId": tgt_cls,
                        "type": "Generalization",
                    })

            # Realization / Implementation
            elif elem.tag.endswith("Realization") or elem_type == "uml:Realization":
                src_cls = elem.attrib.get("client")
                tgt_cls = elem.attrib.get("supplier")
                if src_cls and tgt_cls:
                    associations.append({
                        "id": elem_id,
                        "sourceId": src_cls,
                        "targetId": tgt_cls,
                        "type": "Realization",
                    })

            # Association
            elif not is_assoc_class and (elem.tag.endswith("Association") or elem_type == "uml:Association"):
                owned_ends = elem.findall(".//ownedEnd")

                def _extract_end_ref(end_node: ET.Element) -> Optional[str]:
                    t = end_node.attrib.get("type")
                    if t:
                        return t
                    t_child = end_node.find(".//type")
                    if t_child is not None:
                        for attr in ["{http://schema.omg.org/spec/XMI/2.1}idref", "xmi:idref", "idref", "type"]:
                            val = t_child.attrib.get(attr)
                            if val:
                                return val
                    return None

                src_cls = None
                tgt_cls = None
                src_role = None
                tgt_role = None
                src_mult = None
                tgt_mult = None
                rel_type = "Association"

                if len(owned_ends) >= 2:
                    src_cls = _extract_end_ref(owned_ends[0])
                    tgt_cls = _extract_end_ref(owned_ends[1])
                    src_role = owned_ends[0].attrib.get("name")
                    tgt_role = owned_ends[1].attrib.get("name")
                    src_mult = self._parse_multiplicity(owned_ends[0])
                    tgt_mult = self._parse_multiplicity(owned_ends[1])
                    agg = owned_ends[0].attrib.get("aggregation") or owned_ends[1].attrib.get("aggregation")
                    if agg == "shared":
                        rel_type = "Aggregation"
                    elif agg == "composite":
                        rel_type = "Composition"

                # Fallback to EA connector metadata if src_cls, tgt_cls, roles or multiplicities are missing
                ea_conn = ea_connectors.get(elem_id)
                if ea_conn:
                    if not src_cls:
                        src_cls = ea_conn.get("sourceId")
                    if not tgt_cls:
                        tgt_cls = ea_conn.get("targetId")
                    if not src_role:
                        src_role = ea_conn.get("source_role")
                    if not tgt_role:
                        tgt_role = ea_conn.get("target_role")
                    if not src_mult:
                        src_mult = ea_conn.get("source_multiplicity")
                    if not tgt_mult:
                        tgt_mult = ea_conn.get("target_multiplicity")
                    if rel_type == "Association" and ea_conn.get("type"):
                        ea_t = ea_conn.get("type")
                        if ea_t in ["Aggregation", "Composition", "Generalization", "Realization"]:
                            rel_type = ea_t

                if src_cls and tgt_cls and elem_id not in seen_assoc_ids:
                    seen_assoc_ids.add(elem_id)
                    ac_id = ea_assoc_class_links.get(elem_id)
                    associations.append({
                        "id": elem_id,
                        "sourceId": src_cls,
                        "targetId": tgt_cls,
                        "type": rel_type,
                        "name": name or "",
                        "source_role": src_role,
                        "target_role": tgt_role,
                        "source_multiplicity": src_mult,
                        "target_multiplicity": tgt_mult,
                        "association_class_id": ac_id,
                    })

        # 3. Add any remaining EA connectors that were not defined as uml:Association packagedElements
        for conn_id, conn in ea_connectors.items():
            if conn_id not in seen_assoc_ids and conn.get("sourceId") and conn.get("targetId"):
                seen_assoc_ids.add(conn_id)
                associations.append({
                    "id": conn_id,
                    "sourceId": conn["sourceId"],
                    "targetId": conn["targetId"],
                    "type": conn.get("type", "Association"),
                    "name": "",
                    "source_role": conn.get("source_role"),
                    "target_role": conn.get("target_role"),
                    "source_multiplicity": conn.get("source_multiplicity"),
                    "target_multiplicity": conn.get("target_multiplicity"),
                    "association_class_id": ea_assoc_class_links.get(conn_id),
                })

        # Resolve vertical collisions / overlapping tables
        self._resolve_table_overlaps(classes)

        return {
            "packages": packages,
            "classes": classes,
            "associations": associations,
        }
