"""
Motor de Exportación e Importación de XMI 2.1 compatible con Enterprise Architect (Sparx EA) y OMG UML 2.x.
"""
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


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
    return f"EAID_{clean}"


class XmiExporter:
    """
    Serializador a formato XMI 2.1 con extensiones visuales de Enterprise Architect.
    """

    def export_board(
        self,
        project_name: str,
        board_name: str,
        classes: List[Dict[str, Any]],
        associations: List[Dict[str, Any]],
        board_elements: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> str:
        """
        Exporta el modelo y la vista del diagrama a XML XMI 2.1.
        """
        board_elements = board_elements or {}
        model_id = _make_ea_id(str(uuid.uuid4()))
        pkg_id = _make_ea_id(str(uuid.uuid4()))
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

        # <xmi:Documentation>
        doc = ET.SubElement(root, "xmi:Documentation")
        doc.set("exporter", "dgram")
        doc.set("exporterVersion", "2.0")

        # <uml:Model>
        model = ET.SubElement(
            root,
            "uml:Model",
            {
                "xmi:type": "uml:Model",
                "name": project_name or "Modelo UML",
                "xmi:id": model_id,
            },
        )

        # <packagedElement xmi:type="uml:Package">
        pkg = ET.SubElement(
            model,
            "packagedElement",
            {
                "xmi:type": "uml:Package",
                "name": "Logical View",
                "xmi:id": pkg_id,
            },
        )

        class_id_map: Dict[str, str] = {}

        # 1. Clases e Interfaces
        for cls in classes:
            c_id = cls.get("id") or str(uuid.uuid4())
            ea_class_id = _make_ea_id(c_id)
            class_id_map[c_id] = ea_class_id
            class_id_map[cls.get("name", "")] = ea_class_id

            is_interface = cls.get("element_type") == "interface" or cls.get("stereotype") == "interface"
            uml_type = "uml:Interface" if is_interface else "uml:Class"

            cls_elem = ET.SubElement(
                pkg,
                "packagedElement",
                {
                    "xmi:type": uml_type,
                    "xmi:id": ea_class_id,
                    "name": cls.get("name", "Class1"),
                },
            )
            if cls.get("is_abstract"):
                cls_elem.set("isAbstract", "true")

            # Atributos / Propiedades
            for attr in cls.get("attributes", []):
                attr_id = _make_ea_id(attr.get("id") or str(uuid.uuid4()))
                vis = VISIBILITY_MAP_TO_UML.get(str(attr.get("visibility", "public")).lower(), "public")
                
                prop = ET.SubElement(
                    cls_elem,
                    "ownedAttribute",
                    {
                        "xmi:type": "uml:Property",
                        "xmi:id": attr_id,
                        "name": attr.get("name", "attr"),
                        "visibility": vis,
                    },
                )
                
                # Tipo primitivo o personalizado
                dtype = attr.get("data_type") or attr.get("type") or "String"
                type_ref = ET.SubElement(
                    prop,
                    "type",
                    {
                        "xmi:type": "uml:PrimitiveType",
                        "href": f"http://schema.omg.org/spec/UML/2.1/uml.xml#{dtype}",
                    },
                )

        # 2. Asociaciones y Generalizaciones
        for assoc in associations:
            assoc_id = _make_ea_id(assoc.get("id") or str(uuid.uuid4()))
            src_id = assoc.get("sourceId") or assoc.get("source_class_id") or ""
            tgt_id = assoc.get("targetId") or assoc.get("target_class_id") or ""
            rel_type = str(assoc.get("type", "Association")).strip()

            ea_src = class_id_map.get(src_id, _make_ea_id(src_id))
            ea_tgt = class_id_map.get(tgt_id, _make_ea_id(tgt_id))

            is_gen = rel_type.lower() in ["generalization", "inheritance"]
            is_real = rel_type.lower() in ["realization", "implementation"]

            if is_gen:
                # Find the source class element to append <generalization>
                src_node = pkg.find(f".//*[@xmi:id='{ea_src}']")
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
                    pkg,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Realization",
                        "xmi:id": assoc_id,
                        "supplier": ea_tgt,
                        "client": ea_src,
                    },
                )
            else:
                # Standard Association / Aggregation / Composition
                assoc_elem = ET.SubElement(
                    pkg,
                    "packagedElement",
                    {
                        "xmi:type": "uml:Association",
                        "xmi:id": assoc_id,
                        "name": assoc.get("name") or "",
                    },
                )
                # Ends
                end1 = ET.SubElement(
                    assoc_elem,
                    "memberEnd",
                    {"xmi:idref": f"{assoc_id}_src"},
                )
                end2 = ET.SubElement(
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
                if rel_type.lower() == "aggregation":
                    oe1.set("aggregation", "shared")
                elif rel_type.lower() == "composition":
                    oe1.set("aggregation", "composite")

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

        # 3. <xmi:Extension extender="Enterprise Architect"> (Diagram Layout & Coordinates)
        ext = ET.SubElement(
            root,
            "xmi:Extension",
            {
                "extender": "Enterprise Architect",
                "extenderID": "6.5",
            },
        )
        diagrams_node = ET.SubElement(ext, "diagrams")
        diag_node = ET.SubElement(diagrams_node, "diagram", {"xmi:id": diag_id})
        
        props_node = ET.SubElement(diag_node, "properties")
        props_node.set("name", board_name or "Class Diagram")
        props_node.set("type", "Logical")

        elements_node = ET.SubElement(diag_node, "elements")
        for cls in classes:
            c_id = cls.get("id") or ""
            ea_id = class_id_map.get(c_id, _make_ea_id(c_id))
            pos = board_elements.get(c_id) or cls.get("position") or {"x": 100.0, "y": 100.0}
            px = float(pos.get("x", 100.0))
            py = float(pos.get("y", 100.0))
            w = float(pos.get("w", 220.0))
            h = float(pos.get("h", 160.0))

            # EA geometry format: Left=X;Top=Y;Right=X+W;Bottom=Y+H;
            left = int(px)
            top = int(py)
            right = int(px + w)
            bottom = int(py + h)

            geom_str = f"Left={left};Top={top};Right={right};Bottom={bottom};"
            elem = ET.SubElement(
                elements_node,
                "element",
                {
                    "geometry": geom_str,
                    "subject": ea_id,
                    "seqno": "1",
                    "style": "DUID=EAID_DUID;",
                },
            )

        # Return formatted XML
        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


class XmiImporter:
    """
    Parser robusto para archivos XMI 2.1 / 2.x exportados desde Enterprise Architect u otras herramientas CASE.
    """

    def parse(self, xml_content: str) -> Dict[str, Any]:
        """
        Parsea el contenido XML y retorna la estructura del modelo, clases, atributos, relaciones y posiciones visuales.
        """
        root = ET.fromstring(xml_content)

        # Namespaces handling: search regardless of prefix
        classes: List[Dict[str, Any]] = []
        associations: List[Dict[str, Any]] = []
        positions: Dict[str, Dict[str, float]] = {}

        # 1. Parse EA Geometry extensions if present
        for elem in root.iter():
            if elem.tag.endswith("element") and "geometry" in elem.attrib:
                subject = elem.attrib.get("subject", "")
                geom = elem.attrib.get("geometry", "")
                # Parse Left=...;Top=...;Right=...;Bottom=...;
                parsed_geo = self._parse_ea_geometry(geom)
                if subject and parsed_geo:
                    positions[subject] = parsed_geo

        # 2. Parse Packages, Classes & Interfaces
        for elem in root.iter():
            elem_type = elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type") or elem.attrib.get("xmi:type") or elem.attrib.get("type") or ""
            elem_id = elem.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or elem.attrib.get("xmi:id") or elem.attrib.get("id") or ""
            name = elem.attrib.get("name")

            if not elem_id or not name:
                continue

            if elem_type in ["uml:Class", "uml:Interface", "uml:Enumeration", "uml:DataType"] or elem.tag.endswith("Class") or elem.tag.endswith("Interface"):
                is_abstract = elem.attrib.get("isAbstract", "false").lower() == "true"
                classifier = "interface" if "Interface" in elem_type or elem.tag.endswith("Interface") else "class"

                attributes = []
                # Attributes / Properties
                for child in elem:
                    c_type = child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}type") or child.attrib.get("xmi:type") or child.tag
                    if child.tag.endswith("ownedAttribute") or "Property" in c_type:
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

                        attributes.append({
                            "id": child.attrib.get("{http://schema.omg.org/spec/XMI/2.1}id") or child.attrib.get("xmi:id") or str(uuid.uuid4()),
                            "name": attr_name,
                            "data_type": dtype,
                            "visibility": VISIBILITY_MAP_FROM_UML.get(vis, "public"),
                            "is_pkey": is_pk,
                        })

                # Position from EA extension or default
                pos = positions.get(elem_id, {"x": 100.0 + len(classes) * 40.0, "y": 100.0 + len(classes) * 40.0})

                classes.append({
                    "id": elem_id,
                    "name": name,
                    "element_type": classifier,
                    "is_abstract": is_abstract,
                    "attributes": attributes,
                    "position": pos,
                })

            # Generalization
            if elem.tag.endswith("generalization") or elem_type == "uml:Generalization":
                src_cls = elem.attrib.get("specific") or elem.attrib.get("client")
                tgt_cls = elem.attrib.get("general") or elem.attrib.get("supplier")
                if not src_cls:
                    # Find parent tag
                    pass
                if tgt_cls:
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
            elif elem.tag.endswith("Association") or elem_type == "uml:Association":
                member_ends = [m.attrib.get("xmi:idref") or m.attrib.get("idref") for m in elem.findall(".//memberEnd")]
                owned_ends = elem.findall(".//ownedEnd")
                
                src_cls = None
                tgt_cls = None
                rel_type = "Association"

                if len(owned_ends) >= 2:
                    src_cls = owned_ends[0].attrib.get("type")
                    tgt_cls = owned_ends[1].attrib.get("type")
                    agg = owned_ends[0].attrib.get("aggregation") or owned_ends[1].attrib.get("aggregation")
                    if agg == "shared":
                        rel_type = "Aggregation"
                    elif agg == "composite":
                        rel_type = "Composition"

                if src_cls and tgt_cls:
                    associations.append({
                        "id": elem_id,
                        "sourceId": src_cls,
                        "targetId": tgt_cls,
                        "type": rel_type,
                        "name": name or "",
                    })

        # Match generalization parent if specific was missing
        for cls in classes:
            # Check nested generalizations
            pass

        return {
            "classes": classes,
            "associations": associations,
        }

    def _parse_ea_geometry(self, geom: str) -> Optional[Dict[str, float]]:
        """
        Parsea un string de geometría EA: Left=100;Top=150;Right=320;Bottom=310;
        """
        try:
            parts = [p.strip() for p in geom.split(";") if "=" in p]
            kv = dict(p.split("=", 1) for p in parts)
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
