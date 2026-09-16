"""
Excepciones de dominio para modelado de diagramas (CU3).
"""
from fastapi import HTTPException, status


class DiagramException(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class BoardNotFoundException(DiagramException):
    def __init__(self, detail: str = "Tablero no encontrado"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class InvalidCommandException(DiagramException):
    def __init__(self, detail: str = "Comando inválido"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class GeneralizationCycleException(DiagramException):
    def __init__(self, detail: str = "Se detectó un ciclo de generalización/herencia inválido"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
