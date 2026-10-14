"""
spring_web_generator.py — Generador de Repositorios, DTOs, Mappers, Servicios y Controllers Spring Boot.
"""
from typing import Optional, List, Dict, Set
from app.generation.code.service.java_naming_service import (
    to_pascal_case,
    to_camel_case,
    map_sql_to_java_type,
)


class SpringWebGenerator:
    def __init__(self, base_package: str = "com.dgram.generated"):
        self.base_package = base_package

    def generate_repository(self, class_name: str, id_type: str = "Long") -> str:
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

    def generate_dto(
        self,
        class_name: str,
        attributes: list[dict],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
        src_assocs: list[dict] | None = None,
        class_names: dict[str, str] | None = None,
        class_id_types: dict[str, str] | None = None,
    ) -> str:
        enum_names = enum_names or set()
        datatype_names = datatype_names or set()
        src_assocs = src_assocs or []
        class_names = class_names or {}
        class_id_types = class_id_types or {}
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)
        has_datatypes = any((attr.get("type") in datatype_names) for attr in attributes)
        has_m2m = any(
            str(a.get("type") or "").lower() in ("n:m", "many_to_many", "*:*")
            for a in src_assocs
        )
        has_uuid = any("UUID" in (class_id_types.get(class_names.get(a.get("targetId") or a.get("targetClassId")), "") or "") for a in src_assocs)
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
        if has_m2m:
            lines.append("import java.util.Set;")
        if has_uuid:
            lines.append("import java.util.UUID;")
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

        # Relaciones ManyToOne / OneToOne / ManyToMany en el DTO
        for a in src_assocs:
            tgt_id = a.get("targetId") or a.get("targetClassId")
            tgt_name = class_names.get(tgt_id)
            if not tgt_name or tgt_name in enum_names:
                continue
            rel_type = str(a.get("type") or a.get("relationType") or "").lower()
            role_name = a.get("target_role") or a.get("targetRole") or a.get("name")
            is_m2m = rel_type in ("n:m", "many_to_many", "*:*")
            tgt_id_type = class_id_types.get(tgt_name, "Long")
            if tgt_id_type.startswith("java.util."):
                tgt_id_type = tgt_id_type.split(".")[-1]

            if is_m2m:
                field_name = to_camel_case(role_name or tgt_name) + "Ids"
                lines.append(f"    private Set<{tgt_id_type}> {field_name};")
            else:
                field_name = to_camel_case(role_name or tgt_name) + "Id"
                lines.append(f"    private {tgt_id_type} {field_name};")

        lines.append("}")
        return "\n".join(lines)

    def generate_mapper(
        self,
        class_name: str,
        attributes: list[dict],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
        src_assocs: list[dict] | None = None,
        class_names: dict[str, str] | None = None,
    ) -> str:
        enum_names = enum_names or set()
        datatype_names = datatype_names or set()
        src_assocs = src_assocs or []
        class_names = class_names or {}
        has_enums = any((attr.get("type") in enum_names) for attr in attributes)
        has_datatypes = any((attr.get("type") in datatype_names) for attr in attributes)
        has_m2m = any(
            str(a.get("type") or "").lower() in ("n:m", "many_to_many", "*:*")
            for a in src_assocs
        )
        lines = [
            f"package {self.base_package}.mapper;",
            "",
            f"import {self.base_package}.dto.{class_name}DTO;",
            f"import {self.base_package}.entity.{class_name};",
            "import org.springframework.stereotype.Component;",
        ]
        if has_m2m:
            lines.append("import java.util.stream.Collectors;")
            lines.append("import java.util.HashSet;")
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

        for a in src_assocs:
            tgt_id = a.get("targetId") or a.get("targetClassId")
            tgt_name = class_names.get(tgt_id)
            if not tgt_name or tgt_name in enum_names:
                continue
            rel_type = str(a.get("type") or a.get("relationType") or "").lower()
            role_name = a.get("target_role") or a.get("targetRole") or a.get("name")
            is_m2m = rel_type in ("n:m", "many_to_many", "*:*")

            owner_field = a.get("_owner_field_name") or (to_camel_case(role_name or tgt_name) + ("Set" if is_m2m else ""))
            if is_m2m:
                dto_field = to_camel_case(role_name or tgt_name) + "Ids"
                entity_getter = f"get{to_pascal_case(owner_field)}()"
                lines.append(
                    f"                .{dto_field}(entity.{entity_getter} != null ? "
                    f"entity.{entity_getter}.stream().map(e -> e.getId()).collect(Collectors.toSet()) : new HashSet<>())"
                )
            else:
                dto_field = to_camel_case(role_name or tgt_name) + "Id"
                entity_getter = f"get{to_pascal_case(owner_field)}()"
                lines.append(
                    f"                .{dto_field}(entity.{entity_getter} != null ? entity.{entity_getter}.getId() : null)"
                )

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

    def generate_service(
        self,
        class_name: str,
        id_type: str = "Long",
        is_composite: bool = False,
        attributes: list[dict] | None = None,
        src_assocs: list[dict] | None = None,
        class_names: dict[str, str] | None = None,
        class_id_types: dict[str, str] | None = None,
    ) -> str:
        var_name = to_camel_case(class_name)
        short_id_type = "UUID" if "UUID" in id_type else id_type
        id_class_import = f"\nimport {self.base_package}.entity.{short_id_type};" if short_id_type not in ("Long", "Integer", "UUID") and "." not in short_id_type else ""
        src_assocs = src_assocs or []
        class_names = class_names or {}
        class_id_types = class_id_types or {}

        # Identificar repositorios únicos a inyectar (excluyendo a la propia clase si es autoreferenciada)
        repos_to_inject: dict[str, str] = {}
        for a in src_assocs:
            tgt_id = a.get("targetId") or a.get("targetClassId")
            tgt_name = class_names.get(tgt_id)
            if not tgt_name:
                continue
            if tgt_name != class_name and tgt_name not in repos_to_inject:
                repos_to_inject[tgt_name] = to_camel_case(tgt_name) + "Repository"

        repo_imports = "".join(f"\nimport {self.base_package}.repository.{tgt}Repository;" for tgt in repos_to_inject)
        repo_fields = "".join(f"\n    private final {tgt}Repository {var};" for tgt, var in repos_to_inject.items())
        has_uuid_service = "UUID" in short_id_type or any("UUID" in (class_id_types.get(tgt, "") or "") for tgt in repos_to_inject)
        uuid_import = "\nimport java.util.UUID;" if has_uuid_service else ""

        # Lógica de enlace de relaciones en create y update (para TODAS las asociaciones salientes)
        binding_lines = []
        for a in src_assocs:
            tgt_id = a.get("targetId") or a.get("targetClassId")
            tgt_name = class_names.get(tgt_id)
            if not tgt_name:
                continue
            rel_type = str(a.get("type") or a.get("relationType") or "").lower()
            role_name = a.get("target_role") or a.get("targetRole") or a.get("name")
            is_m2m = rel_type in ("n:m", "many_to_many", "*:*")
            owner_field = a.get("_owner_field_name") or to_camel_case(role_name or tgt_name)
            repo_var = f"{var_name}Repository" if tgt_name == class_name else repos_to_inject.get(tgt_name, to_camel_case(tgt_name) + "Repository")

            if is_m2m:
                dto_field = to_camel_case(role_name or tgt_name) + "Ids"
                prop_name = owner_field if owner_field.endswith("Set") else owner_field + "Set"
                setter = f"set{to_pascal_case(prop_name)}"
                binding_lines.append(
                    f"        if (dto.get{dto_field[0].upper() + dto_field[1:]}() != null) {{\n"
                    f"            entity.{setter}(new java.util.HashSet<>({repo_var}.findAllById(dto.get{dto_field[0].upper() + dto_field[1:]}())));\n"
                    f"        }}"
                )
            else:
                dto_field = to_camel_case(role_name or tgt_name) + "Id"
                setter = f"set{to_pascal_case(owner_field)}"
                binding_lines.append(
                    f"        if (dto.get{dto_field[0].upper() + dto_field[1:]}() != null) {{\n"
                    f"            {repo_var}.findById(dto.get{dto_field[0].upper() + dto_field[1:]}()).ifPresent(entity::{setter});\n"
                    f"        }}"
                )
        relation_binding_code = "\n".join(binding_lines)
        if relation_binding_code:
            relation_binding_code = "\n" + relation_binding_code

        id_set_code = "" if is_composite else f"\n        entity.setId(id);"

        return f"""package {self.base_package}.service;

import {self.base_package}.dto.{class_name}DTO;
import {self.base_package}.entity.{class_name};{id_class_import}{uuid_import}
import {self.base_package}.mapper.{class_name}Mapper;
import {self.base_package}.repository.{class_name}Repository;{repo_imports}
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
    private final {class_name}Mapper {var_name}Mapper;{repo_fields}

    @Transactional(readOnly = true)
    public List<{class_name}DTO> findAll() {{
        return {var_name}Repository.findAll().stream()
                .map({var_name}Mapper::toDTO)
                .collect(Collectors.toList());
    }}

    @Transactional(readOnly = true)
    public Optional<{class_name}DTO> findById({short_id_type} id) {{
        return {var_name}Repository.findById(id)
                .map({var_name}Mapper::toDTO);
    }}

    public {class_name}DTO create({class_name}DTO dto) {{
        {class_name} entity = {var_name}Mapper.toEntity(dto);{relation_binding_code}
        {class_name} saved = {var_name}Repository.save(entity);
        return {var_name}Mapper.toDTO(saved);
    }}

    public Optional<{class_name}DTO> update({short_id_type} id, {class_name}DTO dto) {{
        if (!{var_name}Repository.existsById(id)) {{
            return Optional.empty();
        }}
        {class_name} entity = {var_name}Mapper.toEntity(dto);{id_set_code}{relation_binding_code}
        {class_name} saved = {var_name}Repository.save(entity);
        return Optional.of({var_name}Mapper.toDTO(saved));
    }}

    public boolean deleteById({short_id_type} id) {{
        if (!{var_name}Repository.existsById(id)) {{
            return false;
        }}
        {var_name}Repository.deleteById(id);
        return true;
    }}
}}
"""

    def generate_exception_handler(self) -> str:
        return f"""package {self.base_package}.exception;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.HashMap;
import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {{

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, String>> handleValidationErrors(MethodArgumentNotValidException ex) {{
        Map<String, String> errors = new HashMap<>();
        ex.getBindingResult().getFieldErrors().forEach(error ->
                errors.put(error.getField(), error.getDefaultMessage())
        );
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(errors);
    }}

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<Map<String, String>> handleDataIntegrityViolation(DataIntegrityViolationException ex) {{
        Map<String, String> error = new HashMap<>();
        error.put("error", "Data integrity violation");
        error.put("message", ex.getMostSpecificCause() != null ? ex.getMostSpecificCause().getMessage() : ex.getMessage());
        return ResponseEntity.status(HttpStatus.CONFLICT).body(error);
    }}
}}
"""


    def generate_controller(self, class_name: str, id_type: str = "Long", is_composite: bool = False) -> str:
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
