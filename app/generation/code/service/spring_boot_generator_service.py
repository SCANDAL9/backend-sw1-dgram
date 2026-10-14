"""
spring_boot_generator_service.py — Master orchestrator for generating Java 21 / Spring Boot 3 projects.
Coordinates entity, web, and configuration artifact generators.
"""
from typing import Any
from app.generation.code.service.java_naming_service import (
    sanitize_java_identifier,
    to_pascal_case,
    to_camel_case,
    sanitize_enum_literal,
    map_sql_to_java_type,
)
from app.generation.code.service.spring_entity_generator import SpringEntityGenerator
from app.generation.code.service.spring_web_generator import SpringWebGenerator
from app.generation.code.service.spring_project_config_generator import SpringProjectConfigGenerator


class SpringBootGenerator:
    def __init__(self, base_package: str = "com.dgram.generated"):
        self.base_package = base_package
        self.entity_gen = SpringEntityGenerator(base_package=base_package)
        self.web_gen = SpringWebGenerator(base_package=base_package)
        self.config_gen = SpringProjectConfigGenerator(base_package=base_package)

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

        # Precalcular el identificador del campo Java en la entidad dueña (source) para alinear mappedBy en JPA
        for cname, c in entities.items():
            cid = c.get("id")
            c_attrs = c.get("attributes") or c.get("columns") or []
            used_field_names = {to_camel_case(attr.get("name") or "attr") for attr in c_attrs}
            for a in assocs_by_source.get(cid, []):
                tgt_id = a.get("targetId") or a.get("targetClassId")
                tgt_name = class_names.get(tgt_id)
                if not tgt_name or tgt_name in enum_name_set:
                    continue
                rel_type = str(a.get("type") or a.get("relationType") or "").lower()
                src_mult = str(a.get("source_multiplicity") or a.get("sourceMultiplicity") or a.get("multiplicity") or "").strip()
                tgt_mult = str(a.get("target_multiplicity") or a.get("targetMultiplicity") or "").strip()
                is_m2m = rel_type in ("n:m", "many_to_many", "*:*") or ("*" in src_mult and "*" in tgt_mult)
                role_name = a.get("target_role") or a.get("targetRole") or a.get("name")
                base_name = to_camel_case(role_name or tgt_name)
                if is_m2m:
                    base_name += "Set"
                field_name = base_name
                counter = 2
                while field_name in used_field_names:
                    field_name = f"{base_name}{counter}"
                    counter += 1
                used_field_names.add(field_name)
                a["_owner_field_name"] = field_name

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

        # 3. Precalcular tipos de ID por entidad
        class_id_types: dict[str, str] = {}
        for cname, c in entities.items():
            attributes = c.get("attributes") or c.get("columns") or []
            pk_attrs = [
                attr for attr in attributes
                if bool(attr.get("pk", False) or attr.get("is_pkey", False) or attr.get("is_primary_key", False))
            ]
            if len(pk_attrs) == 1:
                class_id_types[cname] = map_sql_to_java_type(pk_attrs[0].get("type", "BIGINT"))
            elif len(pk_attrs) > 1:
                class_id_types[cname] = f"{cname}Id"
            else:
                class_id_types[cname] = "Long"

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
                dto_code = self._generate_dto(
                    cname,
                    attributes,
                    enum_names=enum_name_set,
                    datatype_names=datatype_name_set,
                    src_assocs=src_assocs,
                    class_names=class_names,
                    class_id_types=class_id_types,
                )
                files[f"src/main/java/{self.base_package.replace('.', '/')}/dto/{cname}DTO.java"] = dto_code

                # Mapper
                mapper_code = self._generate_mapper(
                    cname,
                    attributes,
                    enum_names=enum_name_set,
                    datatype_names=datatype_name_set,
                    src_assocs=src_assocs,
                    class_names=class_names,
                )
                files[f"src/main/java/{self.base_package.replace('.', '/')}/mapper/{cname}Mapper.java"] = mapper_code

                # Service
                service_code = self._generate_service(
                    cname,
                    id_type=id_type,
                    is_composite=is_composite,
                    attributes=attributes,
                    src_assocs=src_assocs,
                    class_names=class_names,
                    class_id_types=class_id_types,
                )
                files[f"src/main/java/{self.base_package.replace('.', '/')}/service/{cname}Service.java"] = service_code

                # Controller
                ctrl_code = self._generate_controller(cname, id_type=id_type, is_composite=is_composite)
                files[f"src/main/java/{self.base_package.replace('.', '/')}/controller/{cname}Controller.java"] = ctrl_code

        # 3.b GlobalExceptionHandler
        files[f"src/main/java/{self.base_package.replace('.', '/')}/exception/GlobalExceptionHandler.java"] = self.web_gen.generate_exception_handler()

        # 4. Application Main class
        files[f"src/main/java/{self.base_package.replace('.', '/')}/Application.java"] = self._generate_main_app()

        # 5. Application Test class
        files[f"src/test/java/{self.base_package.replace('.', '/')}/ApplicationTests.java"] = self._generate_test_app()

        # 6. application.properties
        files["src/main/resources/application.properties"] = self._generate_application_properties()
        files["src/test/resources/application.properties"] = self.config_gen.generate_test_application_properties()

        # 7. pom.xml
        files["pom.xml"] = self._generate_pom_xml()

        return files

    # Delegation methods for backwards compatibility and specialized testing
    def _generate_enum(self, enum_name: str, attributes: list[dict]) -> str:
        return self.entity_gen.generate_enum(enum_name, attributes)

    def _generate_interface(self, interface_name: str, attributes: list[dict], enum_names: set[str] | None = None) -> str:
        return self.entity_gen.generate_interface(interface_name, attributes, enum_names)

    def _generate_embeddable(self, class_name: str, attributes: list[dict], enum_names: set[str] | None = None) -> str:
        return self.entity_gen.generate_embeddable(class_name, attributes, enum_names)

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
        return self.entity_gen.generate_entity(
            class_name=class_name,
            attributes=attributes,
            src_assocs=src_assocs,
            tgt_assocs=tgt_assocs,
            class_names=class_names,
            enum_names=enum_names,
            datatype_names=datatype_names,
            is_abstract=is_abstract,
            parent_name=parent_name,
        )

    def _generate_id_class(self, class_name: str, pk_attributes: list[dict]) -> str:
        return self.entity_gen.generate_id_class(class_name, pk_attributes)

    def _generate_repository(self, class_name: str, id_type: str = "Long") -> str:
        return self.web_gen.generate_repository(class_name, id_type)

    def _generate_dto(
        self,
        class_name: str,
        attributes: list[dict],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
        src_assocs: list[dict] | None = None,
        class_names: dict[str, str] | None = None,
        class_id_types: dict[str, str] | None = None,
    ) -> str:
        return self.web_gen.generate_dto(
            class_name=class_name,
            attributes=attributes,
            enum_names=enum_names,
            datatype_names=datatype_names,
            src_assocs=src_assocs,
            class_names=class_names,
            class_id_types=class_id_types,
        )

    def _generate_mapper(
        self,
        class_name: str,
        attributes: list[dict],
        enum_names: set[str] | None = None,
        datatype_names: set[str] | None = None,
        src_assocs: list[dict] | None = None,
        class_names: dict[str, str] | None = None,
    ) -> str:
        return self.web_gen.generate_mapper(
            class_name=class_name,
            attributes=attributes,
            enum_names=enum_names,
            datatype_names=datatype_names,
            src_assocs=src_assocs,
            class_names=class_names,
        )

    def _generate_service(
        self,
        class_name: str,
        id_type: str = "Long",
        is_composite: bool = False,
        attributes: list[dict] | None = None,
        src_assocs: list[dict] | None = None,
        class_names: dict[str, str] | None = None,
        class_id_types: dict[str, str] | None = None,
    ) -> str:
        return self.web_gen.generate_service(
            class_name=class_name,
            id_type=id_type,
            is_composite=is_composite,
            attributes=attributes,
            src_assocs=src_assocs,
            class_names=class_names,
            class_id_types=class_id_types,
        )

    def _generate_controller(self, class_name: str, id_type: str = "Long", is_composite: bool = False) -> str:
        return self.web_gen.generate_controller(class_name, id_type, is_composite)

    def _generate_main_app(self) -> str:
        return self.config_gen.generate_main_app()

    def _generate_test_app(self) -> str:
        return self.config_gen.generate_test_app()

    def _generate_application_properties(self) -> str:
        return self.config_gen.generate_application_properties()

    def _generate_pom_xml(self) -> str:
        return self.config_gen.generate_pom_xml()
