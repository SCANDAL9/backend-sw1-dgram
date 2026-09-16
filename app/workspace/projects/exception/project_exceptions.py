"""
Excepciones de dominio para Proyectos y Colaboración.
"""
from fastapi import HTTPException, status


class ProjectException(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class ProjectNotFoundException(ProjectException):
    def __init__(self, detail: str = "Proyecto no encontrado"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class InsufficientPermissionsException(ProjectException):
    def __init__(self, detail: str = "Permisos insuficientes para esta operación"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class MemberNotFoundException(ProjectException):
    def __init__(self, detail: str = "Miembro no encontrado en el proyecto"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
