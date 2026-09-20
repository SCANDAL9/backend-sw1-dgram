"""
Excepciones de dominio para autenticación y usuarios.
"""
from fastapi import HTTPException, status


class AuthException(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class InvalidCredentialsException(AuthException):
    def __init__(self, detail: str = "Credenciales incorrectas"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class UserAlreadyExistsException(AuthException):
    def __init__(self, detail: str = "Ya existe un usuario registrado con este correo"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class UserNotFoundException(AuthException):
    def __init__(self, detail: str = "Usuario no encontrado"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class InvalidTokenException(AuthException):
    def __init__(self, detail: str = "Token inválido o no reconocido"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class TokenExpiredException(AuthException):
    def __init__(self, detail: str = "El token ha expirado o ya fue utilizado"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
