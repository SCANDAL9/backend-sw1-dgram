"""
Schema Exceptions — Custom exceptions for schema parsing, XMI transformation, and DDL export.
"""

class SchemaException(Exception):
    """Base exception for schema operations."""
    pass


class XmiParsingError(SchemaException):
    """Raised when an XMI XML document cannot be parsed or validated."""
    pass


class SchemaExportError(SchemaException):
    """Raised when an error occurs during schema generation or export."""
    pass
