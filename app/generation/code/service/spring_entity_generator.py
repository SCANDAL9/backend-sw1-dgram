"""
spring_entity_generator.py — Generador de clasificadores Java: Enums, Interfaces, Embeddables, Entities e IdClasses.
"""
from typing import Optional, List, Dict, Set
from app.generation.code.service.java_naming_service import (
    to_camel_case,
    sanitize_enum_literal,
    map_sql_to_java_type,
)


class SpringEntityGenerator:
    def __init__(self, base_package: str = "com.dgram.generated"):
        self.base_package = base_package

    def generate_enum(self, enum_name: str, attributes: list[dict]) -> str:
        literals = []
        for attr in attributes:
            raw_name = attr.get("name") or "VAL"
            literals.append(sanitize_enum_literal(raw_name))

        if not literals:
            literals = ["DEFAULT_VALUE"]

        lines = [
            f"package {self.base_package}.enums;",
            "",
            f"public enum {enum_name} {{",
            "    " + ",\n    ".join(literals) + ";",
            "}",
        ]
        return "\n".join(lines)

    def generate_interface(
        self, interface_name: str, attributes: list[dict], enum_names: set[str] | None = None
    ) -> str:
        enum_names = enum_names or set()
        has_dates = any(attr.get("type", "").upper() in ("DATE", "DATETIME", "TIMESTAMP") for attr in attributes)
        has_uuid = any(attr.get("type", "").upper() in ("UUID",) for attr in attributes)

        imports = [
            f"package {self.base_package}.service;",
            "",
        ]
        if has_dates or has_uuid:
            imports.append("import java.util.*;")
            imports.append("import java.time.*;")
        if any(attr.get("type") in enum_names for attr in attributes):
            imports.append(f"import {self.base_package}.enums.*;")
        if imports[-1] != "":
            imports.append("")

        lines = imports + [
            f"public interface {interface_name} {{",
        ]
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "method")
            raw_type = attr.get("type") or attr.get("data_type") or "void"
            if raw_type.lower() == "void":
                ret_type = "void"
            elif raw_type in enum_names:
                ret_type = raw_type
            else:
                ret_type = map_sql_to_java_type(raw_type)
            lines.append(f"    {ret_type} {name}();")
        lines.append("}")
        return "\n".join(lines)

    def generate_embeddable(
        self, class_name: str, attributes: list[dict], enum_names: set[str] | None = None
    ) -> str:
        enum_names = enum_names or set()
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)

        imports = [
            f"package {self.base_package}.model;",
            "",
            "import jakarta.persistence.*;",
            "import java.util.*;",
            "import lombok.Getter;",
            "import lombok.Setter;",
            "import lombok.NoArgsConstructor;",
            "import lombok.AllArgsConstructor;",
            "import lombok.Builder;",
        ]
        if has_enums:
            imports.append(f"import {self.base_package}.enums.*;")

        imports.append("")
        imports.append("@Embeddable")
        imports.append("@Getter")
        imports.append("@Setter")
        imports.append("@NoArgsConstructor")
        imports.append("@AllArgsConstructor")
        imports.append("@Builder")
        imports.append(f"public class {class_name} {{")
        imports.append("")

        lines = imports
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "field")
            raw_type = attr.get("type", "VARCHAR")
            is_enum_field = raw_type in enum_names
            jtype = raw_type if is_enum_field else map_sql_to_java_type(raw_type)
            vis_symbol = attr.get("visibility", "-")
            vis_map = {"+": "public", "-": "private", "#": "protected", "~": ""}
            java_vis = vis_map.get(vis_symbol, "private")
            vis_prefix = f"{java_vis} " if java_vis else ""

            if is_enum_field:
                lines.append("    @Enumerated(EnumType.STRING)")
                lines.append(f'    @Column(name = "{attr.get("name", name)}")')
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")
            else:
                lines.append(f'    @Column(name = "{attr.get("name", name)}")')
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")

        lines.append("}")
        return "\n".join(lines)

    def generate_id_class(self, class_name: str, pk_attributes: list[dict]) -> str:
        id_class_name = f"{class_name}Id"
        fields: list[tuple[str, str, str]] = []
        for attr in pk_attributes:
            name = to_camel_case(attr.get("name") or "id")
            raw_type = attr.get("type", "BIGINT")
            jtype = map_sql_to_java_type(raw_type)
            vis_symbol = attr.get("visibility", "-")
            vis_map = {"+": "public", "-": "private", "#": "protected", "~": ""}
            java_vis = vis_map.get(vis_symbol, "private")
            vis_prefix = f"{java_vis} " if java_vis else ""
            fields.append((vis_prefix, jtype, name))

        lines = [
            f"package {self.base_package}.entity;",
            "",
            "import java.io.Serializable;",
            "import java.util.Objects;",
            "",
            f"public class {id_class_name} implements Serializable {{",
            "    private static final long serialVersionUID = 1L;",
            "",
        ]

        for vis_prefix, jtype, name in fields:
            lines.append(f"    {vis_prefix}{jtype} {name};")
        lines.append("")

        lines.append(f"    public {id_class_name}() {{")
        lines.append("    }")
        lines.append("")

        params = ", ".join(f"{jtype} {name}" for _, jtype, name in fields)
        lines.append(f"    public {id_class_name}({params}) {{")
        for _, _, name in fields:
            lines.append(f"        this.{name} = {name};")
        lines.append("    }")
        lines.append("")

        for _, jtype, name in fields:
            method_name = name[0].upper() + name[1:]
            lines.append(f"    public {jtype} get{method_name}() {{")
            lines.append(f"        return this.{name};")
            lines.append("    }")
            lines.append("")
            lines.append(f"    public void set{method_name}({jtype} {name}) {{")
            lines.append(f"        this.{name} = {name};")
            lines.append("    }")
            lines.append("")

        lines.append("    @Override")
        lines.append("    public boolean equals(Object o) {")
        lines.append("        if (this == o) return true;")
        lines.append("        if (o == null || getClass() != o.getClass()) return false;")
        lines.append(f"        {id_class_name} that = ({id_class_name}) o;")
        equals_conds = " &&\n               ".join(f"Objects.equals({name}, that.{name})" for _, _, name in fields)
        lines.append(f"        return {equals_conds};")
        lines.append("    }")
        lines.append("")

        fields_joined = ", ".join(name for _, _, name in fields)
        lines.append("    @Override")
        lines.append("    public int hashCode() {")
        lines.append(f"        return Objects.hash({fields_joined});")
        lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def generate_entity(
        self,
        class_name: str,
        attributes: list[dict],
        src_assocs: list[dict],
        tgt_assocs: list[dict],
        class_names: dict[str, str],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
        is_abstract: bool = False,
        parent_name: str | None = None,
    ) -> str:
        enum_names = enum_names or set()
        datatype_names = datatype_names or set()
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)
        has_datatypes = any((attr.get("type") in datatype_names) for attr in attributes)

        pk_attrs = [
            attr for attr in attributes
            if bool(attr.get("pk", False) or attr.get("is_pkey", False) or attr.get("is_primary_key", False))
        ]
        is_composite_pk = len(pk_attrs) > 1

        imports = [
            f"package {self.base_package}.entity;",
            "",
            "import jakarta.persistence.*;",
            "import java.util.*;",
            "import lombok.Getter;",
            "import lombok.Setter;",
            "import lombok.NoArgsConstructor;",
            "import lombok.AllArgsConstructor;",
            "import lombok.Builder;",
        ]
        if has_enums:
            imports.append(f"import {self.base_package}.enums.*;")
        if has_datatypes:
            imports.append(f"import {self.base_package}.model.*;")

        imports.append("")
        extends_clause = f" extends {parent_name}" if parent_name else ""

        if is_abstract:
            imports.append("@MappedSuperclass")
            imports.append("@Getter")
            imports.append("@Setter")
            imports.append("@NoArgsConstructor")
            class_decl = f"public abstract class {class_name}{extends_clause} {{"
        else:
            imports.append("@Entity")
            imports.append(f'@Table(name = "{class_name.lower()}")')
            imports.append("@Getter")
            imports.append("@Setter")
            imports.append("@NoArgsConstructor")
            imports.append("@AllArgsConstructor")
            imports.append("@Builder")
            if is_composite_pk:
                imports.append(f"@IdClass({class_name}Id.class)")
            class_decl = f"public class {class_name}{extends_clause} {{"

        lines = imports + [class_decl, ""]

        used_field_names: set[str] = set()

        has_id = False
        # Generar campos a partir de atributos
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "attr")
            used_field_names.add(name)
            raw_type = attr.get("type", "VARCHAR")
            is_enum_field = raw_type in enum_names
            is_datatype_field = raw_type in datatype_names
            jtype = raw_type if (is_enum_field or is_datatype_field) else map_sql_to_java_type(raw_type)
            is_pk = bool(attr.get("pk", False) or attr.get("is_pkey", False) or attr.get("is_primary_key", False))
            is_derived = bool(attr.get("is_derived", False) or attr.get("isDerived", False))
            vis_symbol = attr.get("visibility", "-")
            vis_map = {"+": "public", "-": "private", "#": "protected", "~": ""}
            java_vis = vis_map.get(vis_symbol, "private")
            vis_prefix = f"{java_vis} " if java_vis else ""

            if is_pk:
                has_id = True
                lines.append("    @Id")
                if not is_composite_pk:
                    if jtype in ("Long", "Integer"):
                        lines.append("    @GeneratedValue(strategy = GenerationType.IDENTITY)")
                    elif jtype == "java.util.UUID":
                        lines.append("    @GeneratedValue(strategy = GenerationType.UUID)")
                lines.append(f'    @Column(name = "{attr.get("name", name)}")')
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")
            elif is_derived:
                lines.append("    @Transient")
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")
            elif is_enum_field:
                lines.append("    @Enumerated(EnumType.STRING)")
                lines.append(f'    @Column(name = "{attr.get("name", name)}")')
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")
            elif is_datatype_field:
                lines.append("    @Embedded")
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")
            else:
                lines.append(f'    @Column(name = "{attr.get("name", name)}")')
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")

        if not has_id and not is_abstract and not parent_name:
            lines.insert(len(imports) + 1, "    @Id\n    @GeneratedValue(strategy = GenerationType.IDENTITY)\n    private Long id;\n")
            used_field_names.add("id")

        # Generar relaciones de salida (src_assocs)
        for a in src_assocs:
            tgt_id = a.get("targetId") or a.get("targetClassId")
            tgt_name = class_names.get(tgt_id)
            if not tgt_name or tgt_name in enum_names:
                continue

            rel_type = str(a.get("type") or a.get("relationType") or "").lower()
            src_mult = str(a.get("source_multiplicity") or a.get("sourceMultiplicity") or a.get("multiplicity") or "").strip()
            tgt_mult = str(a.get("target_multiplicity") or a.get("targetMultiplicity") or "").strip()
            is_m2m = rel_type in ("n:m", "many_to_many", "*:*") or ("*" in src_mult and "*" in tgt_mult)
            is_o2o = rel_type in ("1:1", "one_to_one") or (
                ("1" in src_mult or "0..1" in src_mult) and ("1" in tgt_mult or "0..1" in tgt_mult) and not is_m2m
            )
            field_name = a.get("_owner_field_name")
            if not field_name:
                role_name = a.get("target_role") or a.get("targetRole") or a.get("name")
                base_name = to_camel_case(role_name or tgt_name) + ("Set" if is_m2m else "")
                field_name = base_name
                counter = 2
                while field_name in used_field_names:
                    field_name = f"{base_name}{counter}"
                    counter += 1
                used_field_names.add(field_name)
            else:
                used_field_names.add(field_name)

            if is_m2m:
                join_table = f"{class_name.lower()}_{tgt_name.lower()}"
                lines.append("    @ManyToMany(fetch = FetchType.LAZY)")
                lines.append(f"    @JoinTable(")
                lines.append(f'        name = "{join_table}",')
                lines.append(f'        joinColumns = @JoinColumn(name = "{to_camel_case(class_name)}_id"),')
                lines.append(f'        inverseJoinColumns = @JoinColumn(name = "{to_camel_case(tgt_name)}_id")')
                lines.append("    )")
                lines.append(f"    private Set<{tgt_name}> {field_name} = new HashSet<>();")
                lines.append("")
            elif is_o2o:
                lines.append("    @OneToOne(fetch = FetchType.LAZY)")
                lines.append(f'    @JoinColumn(name = "{field_name}_id", unique = true)')
                lines.append(f"    private {tgt_name} {field_name};")
                lines.append("")
            else:
                lines.append("    @ManyToOne(fetch = FetchType.LAZY)")
                lines.append(f'    @JoinColumn(name = "{field_name}_id")')
                lines.append(f"    private {tgt_name} {field_name};")
                lines.append("")

        # Generar relaciones de entrada (tgt_assocs)
        for a in tgt_assocs:
            src_id = a.get("sourceId") or a.get("sourceClassId")
            src_name = class_names.get(src_id)
            if not src_name or src_name in enum_names:
                continue

            rel_type = str(a.get("type") or a.get("relationType") or "").lower()
            src_mult = str(a.get("source_multiplicity") or a.get("sourceMultiplicity") or a.get("multiplicity") or "").strip()
            tgt_mult = str(a.get("target_multiplicity") or a.get("targetMultiplicity") or "").strip()
            is_m2m = rel_type in ("n:m", "many_to_many", "*:*") or ("*" in src_mult and "*" in tgt_mult)
            is_o2o = rel_type in ("1:1", "one_to_one") or (
                ("1" in src_mult or "0..1" in src_mult) and ("1" in tgt_mult or "0..1" in tgt_mult) and not is_m2m
            )
            role_name = a.get("source_role") or a.get("sourceRole")
            owner_field = a.get("_owner_field_name")

            if is_m2m:
                base_name = to_camel_case(role_name or src_name) + "Set"
                field_name = base_name
                counter = 2
                while field_name in used_field_names:
                    field_name = f"{base_name}{counter}"
                    counter += 1
                used_field_names.add(field_name)

                mapped_by_prop = owner_field if owner_field else f"{to_camel_case(class_name)}Set"
                lines.append(f'    @ManyToMany(mappedBy = "{mapped_by_prop}")')
                lines.append(f"    private Set<{src_name}> {field_name} = new HashSet<>();")
                lines.append("")
            elif is_o2o:
                base_name = to_camel_case(role_name or src_name)
                field_name = base_name
                counter = 2
                while field_name in used_field_names:
                    field_name = f"{base_name}{counter}"
                    counter += 1
                used_field_names.add(field_name)

                mapped_by_prop = owner_field if owner_field else to_camel_case(class_name)
                lines.append(f'    @OneToOne(mappedBy = "{mapped_by_prop}", cascade = CascadeType.ALL)')
                lines.append(f"    private {src_name} {field_name};")
                lines.append("")
            else:
                base_name = to_camel_case(role_name or src_name) + "List"
                field_name = base_name
                counter = 2
                while field_name in used_field_names:
                    field_name = f"{base_name}{counter}"
                    counter += 1
                used_field_names.add(field_name)

                mapped_by_prop = owner_field if owner_field else to_camel_case(class_name)
                lines.append(f'    @OneToMany(mappedBy = "{mapped_by_prop}", cascade = CascadeType.ALL, orphanRemoval = true)')
                lines.append(f"    private List<{src_name}> {field_name} = new ArrayList<>();")
                lines.append("")

        lines.append("}")
        return "\n".join(lines)
