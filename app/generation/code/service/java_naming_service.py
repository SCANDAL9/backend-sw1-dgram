"""
java_naming_service.py — Sanitización de identificadores y mapeo de tipos SQL a Java.
"""
import re


JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "record", "sealed",
    "non-sealed", "permits", "yield", "var", "true", "false", "null"
}


def sanitize_java_identifier(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "Entity_" + cleaned
    if cleaned.lower() in JAVA_KEYWORDS:
        cleaned = f"Item_{cleaned}"
    return cleaned


def to_pascal_case(name: str) -> str:
    words = re.split(r"[_\s\-]+", name)
    result = "".join(w[0].upper() + w[1:] if w else "" for w in words)
    if not result:
        result = "ClassElement"
    if result.lower() in JAVA_KEYWORDS:
        result = f"Model{result}"
    return result


def to_camel_case(name: str) -> str:
    pascal = to_pascal_case(name)
    camel = pascal[0].lower() + pascal[1:] if pascal else "element"
    if camel.lower() in JAVA_KEYWORDS:
        camel = f"{camel}Field"
    return camel


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
