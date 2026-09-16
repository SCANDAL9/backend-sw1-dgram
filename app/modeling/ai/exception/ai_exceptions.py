"""
AI Exceptions — Custom domain exceptions for AI modeling operations.
"""

class AIException(Exception):
    """Base exception for AI operations."""
    pass


class AISessionNotFoundError(AIException):
    """Raised when an AI conversation or guide session is not found."""
    pass


class AIExecutionError(AIException):
    """Raised when an AI model invocation or ADK tool runner fails."""
    pass
