"""
Codegen Exceptions — Custom domain exceptions for Spring Boot Java code generation.
"""

class CodegenException(Exception):
    """Base exception for code generation operations."""
    pass


class TemplateRenderingError(CodegenException):
    """Raised when rendering a Java/Spring Boot Jinja template fails."""
    pass


class InvalidDiagramStateError(CodegenException):
    """Raised when the diagram state cannot be translated into valid code."""
    pass
