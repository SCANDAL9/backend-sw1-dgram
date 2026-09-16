"""
spring_boot_generator.py — Generador de código Java Spring Boot (JPA / REST / Repositories)
a partir de clasificadores UML normalizados (class_element, attribute, association).

Genera:
  1. Enums Java (public enum en el paquete .enums)
  2. Interfaces de servicio (public interface en .service)
  3. Entidades JPA con anotaciones @Entity, @Table, @Id, @Column, @ManyToOne, @OneToMany, @Enumerated
  4. Repositorios Spring Data JPA (@Repository JpaRepository) para entidades concretas
  5. DTOs (Clases de transferencia)
  6. Controllers REST (@RestController, @RequestMapping, CRUD endpoints)
  7. application.properties de configuración base
  8. pom.xml listo para compilar con Maven y Java 17
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
        entities: dict[str, dict] = {}

        for c in classes:
            cid = c.get("id")
            cname = class_names.get(cid, "Entity")
            elem_type = (c.get("element_type") or c.get("elementType") or c.get("stereotype") or "").lower()
            if elem_type in ("enumeration", "enum"):
                enums[cname] = c
            elif elem_type == "interface":
                interfaces[cname] = c
            else:
                entities[cname] = c

        enum_name_set = set(enums.keys())

        # Indexar asociaciones por source y target
        assocs_by_source: dict[str, list[dict]] = {}
        assocs_by_target: dict[str, list[dict]] = {}
        for a in associations:
            src = a.get("sourceId") or a.get("sourceClassId")
            tgt = a.get("targetId") or a.get("targetClassId")
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
            files[f"src/main/java/{self.base_package.replace('.', '/')}/service/{iname}.java"] = self._generate_interface(iname, attributes)

        # 3. Generar Entidades, Repositorios, DTOs y Controllers
        for cname, c in entities.items():
            cid = c.get("id")
            attributes = c.get("attributes") or c.get("columns") or []
            src_assocs = assocs_by_source.get(cid, [])
            tgt_assocs = assocs_by_target.get(cid, [])
            is_abs = bool(c.get("is_abstract", False) or c.get("isAbstract", False) or (c.get("element_type") == "abstract_class"))

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
            entity_code = self._generate_entity(cname, attributes, src_assocs, tgt_assocs, class_names, enum_names=enum_name_set, is_abstract=is_abs)
            files[f"src/main/java/{self.base_package.replace('.', '/')}/entity/{cname}.java"] = entity_code

            # Repositorios, DTOs y Controllers solo para entidades no abstractas
            if not is_abs:
                # Repository
                repo_code = self._generate_repository(cname, id_type=id_type)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/repository/{cname}Repository.java"] = repo_code

                # DTO
                dto_code = self._generate_dto(cname, attributes, enum_names=enum_name_set)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/dto/{cname}DTO.java"] = dto_code

                # Controller
                ctrl_code = self._generate_controller(cname, id_type=id_type, is_composite=is_composite)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/controller/{cname}Controller.java"] = ctrl_code

        # 4. Application Main class
        files[f"src/main/java/{self.base_package.replace('.', '/')}/Application.java"] = self._generate_main_app()

        # 5. application.properties
        files["src/main/resources/application.properties"] = self._generate_application_properties()

        # 6. pom.xml
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

    def _generate_interface(self, interface_name: str, attributes: list[dict]) -> str:
        lines = [
            f"package {self.base_package}.service;",
            "",
            f"public interface {interface_name} {{",
        ]
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "method")
            lines.append(f"    void {name}();")
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
        is_abstract: bool = False,
    ) -> str:
        enum_names = enum_names or set()
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)

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

        imports.append("")
        if is_abstract:
            imports.append("@MappedSuperclass")
            imports.append("@Getter")
            imports.append("@Setter")
            imports.append("@NoArgsConstructor")
            class_decl = f"public abstract class {class_name} {{"
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
            class_decl = f"public class {class_name} {{"

        lines = imports + [class_decl, ""]


        has_id = False
        # Generar campos a partir de atributos
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "attr")
            raw_type = attr.get("type", "VARCHAR")
            is_enum_field = raw_type in enum_names
            jtype = raw_type if is_enum_field else map_sql_to_java_type(raw_type)
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
            else:
                lines.append(f'    @Column(name = "{attr.get("name", name)}")')
                lines.append(f"    {vis_prefix}{jtype} {name};")
                lines.append("")

        if not has_id and not is_abstract:
            # Añadir ID por defecto si no se especificó PK
            lines.insert(len(imports) + 1, "    @Id\n    @GeneratedValue(strategy = GenerationType.IDENTITY)\n    private Long id;\n")

        # Generar relaciones
        for a in src_assocs:
            tgt_id = a.get("targetId") or a.get("targetClassId")
            tgt_name = class_names.get(tgt_id)
            if not tgt_name or tgt_name in enum_names:
                continue
            field_name = to_camel_case(tgt_name)
            lines.append("    @ManyToOne(fetch = FetchType.LAZY)")
            lines.append(f'    @JoinColumn(name = "{field_name}_id")')
            lines.append(f"    private {tgt_name} {field_name};")
            lines.append("")

        for a in tgt_assocs:
            src_id = a.get("sourceId") or a.get("sourceClassId")
            src_name = class_names.get(src_id)
            if not src_name or src_name in enum_names:
                continue
            field_name = to_camel_case(src_name) + "List"
            lines.append(f'    @OneToMany(mappedBy = "{to_camel_case(class_name)}", cascade = CascadeType.ALL, orphanRemoval = true)')
            lines.append(f"    private List<{src_name}> {field_name} = new ArrayList<>();")
            lines.append("")

        # Getters and Setters placeholder
        lines.append("    // Constructors, Getters & Setters")
        lines.append(f"    public {class_name}() {{}}")
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

    def _generate_dto(self, class_name: str, attributes: list[dict], enum_names: set[str] | None = None) -> str:
        enum_names = enum_names or set()
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)
        lines = [
            f"package {self.base_package}.dto;",
            "",
        ]
        if has_enums:
            lines.append(f"import {self.base_package}.enums.*;")
            lines.append("")

        lines.append(f"public class {class_name}DTO {{")
        for attr in attributes:
            name = to_camel_case(attr.get("name") or "attr")
            raw_type = attr.get("type", "VARCHAR")
            jtype = raw_type if raw_type in enum_names else map_sql_to_java_type(raw_type)
            lines.append(f"    private {jtype} {name};")

        lines.append("")
        lines.append(f"    public {class_name}DTO() {{}}")
        lines.append("}")
        return "\n".join(lines)

    def _generate_controller(self, class_name: str, id_type: str = "Long", is_composite: bool = False) -> str:
        var_name = to_camel_case(class_name)
        if is_composite:
            return f"""package {self.base_package}.controller;

import {self.base_package}.entity.{class_name};
import {self.base_package}.repository.{class_name}Repository;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/v1/{var_name}s")
@CrossOrigin(origins = "*")
public class {class_name}Controller {{

    private final {class_name}Repository {var_name}Repository;

    public {class_name}Controller({class_name}Repository {var_name}Repository) {{
        this.{var_name}Repository = {var_name}Repository;
    }}

    @GetMapping
    public List<{class_name}> getAll() {{
        return {var_name}Repository.findAll();
    }}

    @PostMapping
    public {class_name} create(@RequestBody {class_name} entity) {{
        return {var_name}Repository.save(entity);
    }}
}}
"""
        return f"""package {self.base_package}.controller;

import {self.base_package}.entity.{class_name};
import {self.base_package}.repository.{class_name}Repository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/v1/{var_name}s")
@CrossOrigin(origins = "*")
public class {class_name}Controller {{

    private final {class_name}Repository {var_name}Repository;

    public {class_name}Controller({class_name}Repository {var_name}Repository) {{
        this.{var_name}Repository = {var_name}Repository;
    }}

    @GetMapping
    public List<{class_name}> getAll() {{
        return {var_name}Repository.findAll();
    }}

    @GetMapping("/{{id}}")
    public ResponseEntity<{class_name}> getById(@PathVariable {id_type} id) {{
        return {var_name}Repository.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }}

    @PostMapping
    public {class_name} create(@RequestBody {class_name} entity) {{
        return {var_name}Repository.save(entity);
    }}

    @DeleteMapping("/{{id}}")
    public ResponseEntity<Void> delete(@PathVariable {id_type} id) {{
        if (!{var_name}Repository.existsById(id)) {{
            return ResponseEntity.notFound().build();
        }}
        {var_name}Repository.deleteById(id);
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

