"""
spring_boot_generator.py — Generador de código Java Spring Boot (JPA / REST / Repositories)
a partir de clasificadores UML normalizados (class_element, attribute, association).

Genera:
  1. Enums Java (public enum en el paquete .enums)
  2. Interfaces de servicio (public interface en .service para element_type == interface)
  3. Entidades JPA con anotaciones @Entity, @Table, @Id, @Column, @ManyToOne, @OneToMany, @ManyToMany, @OneToOne, @Enumerated
  4. Repositorios Spring Data JPA (@Repository JpaRepository) para entidades concretas
  5. DTOs desacoplados con validaciones Jakarta (@NotNull, @NotBlank, @Size, @Email) y Lombok
  6. Mappers (@Component) para transformación bidireccional Entity <-> DTO
  7. Servicios de negocio (@Service, @Transactional) para entidades concretas
  8. Controllers REST (@RestController, @RequestMapping, CRUD completo con DTOs)
  9. application.properties de configuración base
  10. pom.xml listo para compilar con Maven, Java 21, Spring Boot 3.3.4, Lombok, OpenAPI y Jakarta Validation
  11. ApplicationTests.java en src/test/java/ para verificación de compilación y contexto
"""
import re
from typing import Any
from app.modeling.diagram.entity.uml_entity import AssociationType


def sanitize_java_identifier(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "Entity_" + cleaned
    return cleaned


def to_pascal_case(name: str) -> str:
    words = re.split(r"[_\s\-]+", name)
    result = "".join(w[0].upper() + w[1:] if w else "" for w in words)
    return result or "ClassElement"


def to_camel_case(name: str) -> str:
    pascal = to_pascal_case(name)
    return pascal[0].lower() + pascal[1:] if pascal else "element"


def sanitize_enum_literal(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_").upper()
    if not cleaned or cleaned[0].isdigit():
        cleaned = "VAL_" + cleaned
    return cleaned


def map_sql_to_java_type(sql_type: str, enum_names: set[str] | None = None) -> str:
    if enum_names and sql_type in enum_names:
        return sql_type
    t = (sql_type or "VARCHAR").upper()
    if "INT" in t:
        if "BIG" in t:
            return "Long"
        return "Integer"
    if "FLOAT" in t or "DOUBLE" in t or "DECIMAL" in t or "NUMERIC" in t:
        return "Double"
    if "BOOL" in t:
        return "Boolean"
    if "TIME" in t or "DATE" in t:
        return "java.time.LocalDateTime"
    if "UUID" in t:
        return "java.util.UUID"
    if "JSON" in t or "TEXT" in t:
        return "String"
    return "String"


class SpringBootGenerator:
    def __init__(self, base_package: str = "com.dgram.generated"):
        self.base_package = base_package

    def generate_project_bundle(self, state: dict) -> dict[str, str]:
        """
        Genera un diccionario path -> file_content con el proyecto Spring Boot completo.
        """
        files: dict[str, str] = {}
        classes = state.get("entities") or state.get("classes") or []
        associations = state.get("relations") or state.get("associations") or []

        # Mapa de class_id -> nombre PascalCase
        class_names: dict[str, str] = {
            c.get("id"): to_pascal_case(c.get("name") or "Entity") for c in classes
        }

        # Identificar clasificadores especiales
        enums: dict[str, dict] = {}
        interfaces: dict[str, dict] = {}
        datatypes: dict[str, dict] = {}
        entities: dict[str, dict] = {}

        for c in classes:
            cid = c.get("id")
            cname = class_names.get(cid, "Entity")
            elem_type = (c.get("element_type") or c.get("elementType") or c.get("stereotype") or "").lower()
            if elem_type in ("enumeration", "enum"):
                enums[cname] = c
            elif elem_type == "interface":
                interfaces[cname] = c
            elif elem_type in ("datatype", "data_type"):
                datatypes[cname] = c
            else:
                entities[cname] = c

        enum_name_set = set(enums.keys())
        datatype_name_set = set(datatypes.keys())

        # Identificar relaciones de herencia / generalización
        child_to_parent: dict[str, str] = {}
        # Indexar asociaciones no-herencia por source y target
        assocs_by_source: dict[str, list[dict]] = {}
        assocs_by_target: dict[str, list[dict]] = {}

        for a in associations:
            rel_type = str(a.get("type") or a.get("relationType") or "").lower()
            src = a.get("sourceId") or a.get("sourceClassId")
            tgt = a.get("targetId") or a.get("targetClassId")

            if rel_type in ("generalization", "inheritance"):
                tgt_name = class_names.get(tgt)
                if src and tgt_name:
                    child_to_parent[src] = tgt_name
                continue

            if src:
                assocs_by_source.setdefault(src, []).append(a)
            if tgt:
                assocs_by_target.setdefault(tgt, []).append(a)

        # 1. Generar Enums
        for ename, c in enums.items():
            attributes = c.get("attributes") or c.get("columns") or []
            files[f"src/main/java/{self.base_package.replace('.', '/')}/enums/{ename}.java"] = self._generate_enum(ename, attributes)

        # 2. Generar Interfaces
        for iname, c in interfaces.items():
            attributes = c.get("attributes") or c.get("columns") or []
            files[f"src/main/java/{self.base_package.replace('.', '/')}/service/{iname}.java"] = self._generate_interface(iname, attributes, enum_names=enum_name_set)

        # 2.b Generar DataTypes (@Embeddable Value Objects)
        for dtname, c in datatypes.items():
            attributes = c.get("attributes") or c.get("columns") or []
            files[f"src/main/java/{self.base_package.replace('.', '/')}/model/{dtname}.java"] = self._generate_embeddable(dtname, attributes, enum_names=enum_name_set)

        # 3. Generar Entidades, Repositorios, DTOs, Mappers, Services y Controllers
        for cname, c in entities.items():
            cid = c.get("id")
            attributes = c.get("attributes") or c.get("columns") or []
            src_assocs = assocs_by_source.get(cid, [])
            tgt_assocs = assocs_by_target.get(cid, [])
            is_abs = bool(c.get("is_abstract", False) or c.get("isAbstract", False) or (c.get("element_type") == "abstract_class"))
            parent_name = child_to_parent.get(cid)

            pk_attrs = [
                attr for attr in attributes
                if bool(attr.get("pk", False) or attr.get("is_pkey", False) or attr.get("is_primary_key", False))
            ]
            is_composite = len(pk_attrs) > 1

            # Si es llave compuesta, generar la clase IdClass
            if is_composite:
                id_class_code = self._generate_id_class(cname, pk_attrs)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/entity/{cname}Id.java"] = id_class_code
                id_type = f"{cname}Id"
            elif len(pk_attrs) == 1:
                id_type = map_sql_to_java_type(pk_attrs[0].get("type", "BIGINT"))
            else:
                id_type = "Long"

            # Entity JPA
            entity_code = self._generate_entity(
                cname,
                attributes,
                src_assocs,
                tgt_assocs,
                class_names,
                enum_names=enum_name_set,
                datatype_names=datatype_name_set,
                is_abstract=is_abs,
                parent_name=parent_name,
            )
            files[f"src/main/java/{self.base_package.replace('.', '/')}/entity/{cname}.java"] = entity_code

            # Componentes adicionales solo para entidades no abstractas
            if not is_abs:
                # Repository
                repo_code = self._generate_repository(cname, id_type=id_type)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/repository/{cname}Repository.java"] = repo_code

                # DTO
                dto_code = self._generate_dto(cname, attributes, enum_names=enum_name_set, datatype_names=datatype_name_set)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/dto/{cname}DTO.java"] = dto_code

                # Mapper
                mapper_code = self._generate_mapper(cname, attributes, enum_names=enum_name_set, datatype_names=datatype_name_set)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/mapper/{cname}Mapper.java"] = mapper_code

                # Service
                service_code = self._generate_service(cname, id_type=id_type, is_composite=is_composite, attributes=attributes)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/service/{cname}Service.java"] = service_code

                # Controller
                ctrl_code = self._generate_controller(cname, id_type=id_type, is_composite=is_composite)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/controller/{cname}Controller.java"] = ctrl_code

        # 4. Application Main class
        files[f"src/main/java/{self.base_package.replace('.', '/')}/Application.java"] = self._generate_main_app()

        # 5. Application Test class
        files[f"src/test/java/{self.base_package.replace('.', '/')}/ApplicationTests.java"] = self._generate_test_app()

        # 6. application.properties
        files["src/main/resources/application.properties"] = self._generate_application_properties()

        # 7. pom.xml
        files["pom.xml"] = self._generate_pom_xml()

        return files

    def _generate_enum(self, enum_name: str, attributes: list[dict]) -> str:
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

    def _generate_interface(self, interface_name: str, attributes: list[dict], enum_names: set[str] | None = None) -> str:
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

    def _generate_embeddable(self, class_name: str, attributes: list[dict], enum_names: set[str] | None = None) -> str:
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

    def _generate_entity(
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

        has_id = False
        # Generar campos a partir de atributos
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "attr")
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
            # Añadir ID por defecto si no se especificó PK y no hereda
            lines.insert(len(imports) + 1, "    @Id\n    @GeneratedValue(strategy = GenerationType.IDENTITY)\n    private Long id;\n")

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

            if is_m2m:
                field_name = to_camel_case(tgt_name) + "Set"
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
                field_name = to_camel_case(tgt_name)
                lines.append("    @OneToOne(fetch = FetchType.LAZY)")
                lines.append(f'    @JoinColumn(name = "{field_name}_id", unique = true)')
                lines.append(f"    private {tgt_name} {field_name};")
                lines.append("")
            else:
                # 1:N / ManyToOne por defecto
                field_name = to_camel_case(tgt_name)
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

            if is_m2m:
                field_name = to_camel_case(src_name) + "Set"
                lines.append(f'    @ManyToMany(mappedBy = "{to_camel_case(tgt_name if False else class_name)}Set")')
                lines.append(f"    private Set<{src_name}> {field_name} = new HashSet<>();")
                lines.append("")
            elif is_o2o:
                field_name = to_camel_case(src_name)
                lines.append(f'    @OneToOne(mappedBy = "{to_camel_case(class_name)}", cascade = CascadeType.ALL)')
                lines.append(f"    private {src_name} {field_name};")
                lines.append("")
            else:
                # OneToMany por defecto
                field_name = to_camel_case(src_name) + "List"
                lines.append(f'    @OneToMany(mappedBy = "{to_camel_case(class_name)}", cascade = CascadeType.ALL, orphanRemoval = true)')
                lines.append(f"    private List<{src_name}> {field_name} = new ArrayList<>();")
                lines.append("")

        # Lombok @NoArgsConstructor y @AllArgsConstructor ya generan constructores limpios
        lines.append("}")
        return "\n".join(lines)

    def _generate_id_class(self, class_name: str, pk_attributes: list[dict]) -> str:
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

    def _generate_repository(self, class_name: str, id_type: str = "Long") -> str:
        entity_import = f"import {self.base_package}.entity.{class_name};"
        id_import = f"\nimport {self.base_package}.entity.{id_type};" if id_type != "Long" and "." not in id_type else ""
        return f"""package {self.base_package}.repository;

{entity_import}{id_import}
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface {class_name}Repository extends JpaRepository<{class_name}, {id_type}> {{
}}
"""

    def _generate_dto(
        self,
        class_name: str,
        attributes: list[dict],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
    ) -> str:
        enum_names = enum_names or set()
        datatype_names = datatype_names or set()
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)
        has_datatypes = any((attr.get("type") in datatype_names) for attr in attributes)
        lines = [
            f"package {self.base_package}.dto;",
            "",
            "import jakarta.validation.constraints.*;",
            "import lombok.Getter;",
            "import lombok.Setter;",
            "import lombok.NoArgsConstructor;",
            "import lombok.AllArgsConstructor;",
            "import lombok.Builder;",
        ]
        if has_enums:
            lines.append(f"import {self.base_package}.enums.*;")
        if has_datatypes:
            lines.append(f"import {self.base_package}.model.*;")
        lines.append("")

        lines.append("@Getter")
        lines.append("@Setter")
        lines.append("@NoArgsConstructor")
        lines.append("@AllArgsConstructor")
        lines.append("@Builder")
        lines.append(f"public class {class_name}DTO {{")

        for attr in attributes:
            name = to_camel_case(attr.get("name") or "attr")
            raw_type = attr.get("type", "VARCHAR")
            is_enum_field = raw_type in enum_names
            is_datatype_field = raw_type in datatype_names
            jtype = raw_type if (is_enum_field or is_datatype_field) else map_sql_to_java_type(raw_type)
            is_pk = bool(attr.get("pk", False) or attr.get("is_pkey", False) or attr.get("is_primary_key", False))
            is_nullable = attr.get("nullable", True)

            # Validaciones Jakarta
            if not is_pk and is_nullable is False:
                if jtype == "String":
                    lines.append(f'    @NotBlank(message = "{name} is required")')
                    lines.append(f'    @Size(max = 255, message = "{name} must not exceed 255 characters")')
                else:
                    lines.append(f'    @NotNull(message = "{name} is required")')

            if "email" in name.lower() or "mail" in name.lower():
                lines.append('    @Email(message = "Invalid email format")')

            lines.append(f"    private {jtype} {name};")
            lines.append("")

        lines.append(f"    public {class_name}DTO() {{}}")
        lines.append("}")
        return "\n".join(lines)

    def _generate_mapper(
        self,
        class_name: str,
        attributes: list[dict],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
    ) -> str:
        enum_names = enum_names or set()
        datatype_names = datatype_names or set()
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)
        has_datatypes = any((attr.get("type") in datatype_names) for attr in attributes)
        lines = [
            f"package {self.base_package}.mapper;",
            "",
            f"import {self.base_package}.dto.{class_name}DTO;",
            f"import {self.base_package}.entity.{class_name};",
            "import org.springframework.stereotype.Component;",
        ]
        if has_enums:
            lines.append(f"import {self.base_package}.enums.*;")
        if has_datatypes:
            lines.append(f"import {self.base_package}.model.*;")

        lines.append("")
        lines.append("@Component")
        lines.append(f"public class {class_name}Mapper {{")
        lines.append("")
        lines.append(f"    public {class_name}DTO toDTO({class_name} entity) {{")
        lines.append("        if (entity == null) {")
        lines.append("            return null;")
        lines.append("        }")
        lines.append(f"        return {class_name}DTO.builder()")
        for attr in attributes:
            field = to_camel_case(attr.get("name") or "attr")
            capital_field = field[0].upper() + field[1:]
            lines.append(f"                .{field}(entity.get{capital_field}())")
        lines.append("                .build();")
        lines.append("    }")
        lines.append("")
        lines.append(f"    public {class_name} toEntity({class_name}DTO dto) {{")
        lines.append("        if (dto == null) {")
        lines.append("            return null;")
        lines.append("        }")
        lines.append(f"        return {class_name}.builder()")
        for attr in attributes:
            field = to_camel_case(attr.get("name") or "attr")
            capital_field = field[0].upper() + field[1:]
            lines.append(f"                .{field}(dto.get{capital_field}())")
        lines.append("                .build();")
        lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def _generate_service(
        self,
        class_name: str,
        id_type: str = "Long",
        is_composite: bool = False,
        attributes: list[dict] | None = None,
    ) -> str:
        var_name = to_camel_case(class_name)
        id_class_import = f"\nimport {self.base_package}.entity.{id_type};" if id_type != "Long" and "." not in id_type else ""

        return f"""package {self.base_package}.service;

import {self.base_package}.dto.{class_name}DTO;
import {self.base_package}.entity.{class_name};{id_class_import}
import {self.base_package}.mapper.{class_name}Mapper;
import {self.base_package}.repository.{class_name}Repository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;

@Service
@Transactional
@RequiredArgsConstructor
public class {class_name}Service {{

    private final {class_name}Repository {var_name}Repository;
    private final {class_name}Mapper {var_name}Mapper;

    @Transactional(readOnly = true)
    public List<{class_name}DTO> findAll() {{
        return {var_name}Repository.findAll().stream()
                .map({var_name}Mapper::toDTO)
                .collect(Collectors.toList());
    }}

    @Transactional(readOnly = true)
    public Optional<{class_name}DTO> findById({id_type} id) {{
        return {var_name}Repository.findById(id)
                .map({var_name}Mapper::toDTO);
    }}

    public {class_name}DTO create({class_name}DTO dto) {{
        {class_name} entity = {var_name}Mapper.toEntity(dto);
        {class_name} saved = {var_name}Repository.save(entity);
        return {var_name}Mapper.toDTO(saved);
    }}

    public Optional<{class_name}DTO> update({id_type} id, {class_name}DTO dto) {{
        if (!{var_name}Repository.existsById(id)) {{
            return Optional.empty();
        }}
        {class_name} entity = {var_name}Mapper.toEntity(dto);
        {class_name} saved = {var_name}Repository.save(entity);
        return Optional.of({var_name}Mapper.toDTO(saved));
    }}

    public boolean deleteById({id_type} id) {{
        if (!{var_name}Repository.existsById(id)) {{
            return false;
        }}
        {var_name}Repository.deleteById(id);
        return true;
    }}
}}
"""

    def _generate_controller(self, class_name: str, id_type: str = "Long", is_composite: bool = False) -> str:
        var_name = to_camel_case(class_name)
        id_class_import = f"\nimport {self.base_package}.entity.{id_type};" if id_type != "Long" and "." not in id_type else ""

        if is_composite:
            return f"""package {self.base_package}.controller;

import {self.base_package}.dto.{class_name}DTO;
import {self.base_package}.service.{class_name}Service;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/v1/{var_name}s")
@CrossOrigin(origins = "*")
@RequiredArgsConstructor
public class {class_name}Controller {{

    private final {class_name}Service {var_name}Service;

    @GetMapping
    public List<{class_name}DTO> getAll() {{
        return {var_name}Service.findAll();
    }}

    @PostMapping
    public ResponseEntity<{class_name}DTO> create(@Valid @RequestBody {class_name}DTO dto) {{
        {class_name}DTO created = {var_name}Service.create(dto);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }}
}}
"""
        return f"""package {self.base_package}.controller;

import {self.base_package}.dto.{class_name}DTO;
import {self.base_package}.service.{class_name}Service;{id_class_import}
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/v1/{var_name}s")
@CrossOrigin(origins = "*")
@RequiredArgsConstructor
public class {class_name}Controller {{

    private final {class_name}Service {var_name}Service;

    @GetMapping
    public List<{class_name}DTO> getAll() {{
        return {var_name}Service.findAll();
    }}

    @GetMapping("/{{id}}")
    public ResponseEntity<{class_name}DTO> getById(@PathVariable {id_type} id) {{
        return {var_name}Service.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }}

    @PostMapping
    public ResponseEntity<{class_name}DTO> create(@Valid @RequestBody {class_name}DTO dto) {{
        {class_name}DTO created = {var_name}Service.create(dto);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }}

    @PutMapping("/{{id}}")
    public ResponseEntity<{class_name}DTO> update(@PathVariable {id_type} id, @Valid @RequestBody {class_name}DTO dto) {{
        return {var_name}Service.update(id, dto)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }}

    @DeleteMapping("/{{id}}")
    public ResponseEntity<Void> delete(@PathVariable {id_type} id) {{
        if (!{var_name}Service.deleteById(id)) {{
            return ResponseEntity.notFound().build();
        }}
        return ResponseEntity.noContent().build();
    }}
}}
"""

    def _generate_main_app(self) -> str:
        return f"""package {self.base_package};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class Application {{
    public static void main(String[] args) {{
        SpringApplication.run(Application.class, args);
    }}
}}
"""

    def _generate_test_app(self) -> str:
        return f"""package {self.base_package};

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class ApplicationTests {{

    @Test
    void contextLoads() {{
    }}

}}
"""

    def _generate_application_properties(self) -> str:
        return """spring.application.name=dgram-generated-app
spring.datasource.url=jdbc:postgresql://localhost:5432/dgram_app
spring.datasource.username=postgres
spring.datasource.password=password
spring.jpa.hibernate.ddl-auto=update
spring.jpa.show-sql=true
spring.jpa.properties.hibernate.format_sql=true
server.port=8080
"""

    def _generate_pom_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.3.4</version>
        <relativePath/>
    </parent>
    <groupId>com.dgram</groupId>
    <artifactId>generated-app</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>generated-app</name>
    <description>Generated Spring Boot app from dgram UML diagram</description>
    <properties>
        <java.version>21</java.version>
        <springdoc.version>2.6.0</springdoc.version>
    </properties>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-validation</artifactId>
        </dependency>
        <dependency>
            <groupId>org.projectlombok</groupId>
            <artifactId>lombok</artifactId>
            <optional>true</optional>
        </dependency>
        <dependency>
            <groupId>org.springdoc</groupId>
            <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
            <version>${springdoc.version}</version>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>
    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
                <configuration>
                    <excludes>
                        <exclude>
                            <groupId>org.projectlombok</groupId>
                            <artifactId>lombok</artifactId>
                        </exclude>
                    </excludes>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
"""
