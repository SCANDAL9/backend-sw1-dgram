"""
Schema Exceptions — Custom exceptions for schema parsing, XMI transformation, and DDL export.
"""


class SchemaException(Exception):
    """Base exception for schema operations."""
    pass


class BoardNotFoundException(SchemaException):
    """Raised when a requested board is not found."""
    pass


class XmiParsingError(SchemaException):
    """Raised when an XMI XML document cannot be parsed or validated."""
    pass


class SchemaExportError(SchemaException):
    """Raised when an error occurs during schema generation or export."""
    pass
