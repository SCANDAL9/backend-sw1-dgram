import re
from pydantic import BaseModel, field_validator

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if not any(c.isalpha() for c in v):
        raise ValueError("La contraseña debe contener al menos una letra")
    if not any(c.isdigit() for c in v):
        raise ValueError("La contraseña debe contener al menos un número")
    return v


class UserRegister(BaseModel):
    email: str
    full_name: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean or not EMAIL_REGEX.match(clean):
            raise ValueError("El formato de correo electrónico no es válido")
        return clean

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        clean = v.strip()
        if len(clean) < 2:
            raise ValueError("El nombre completo debe tener al menos 2 caracteres")
        return clean

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_strength(v)


class UserLogin(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_login(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean:
            raise ValueError("El correo es requerido")
        return clean

    @field_validator("password")
    @classmethod
    def validate_password_login(cls, v: str) -> str:
        if not v:
            raise ValueError("La contraseña es requerida")
        return v


class UserProfile(BaseModel):
    id: str
    full_name: str
    email: str
    avatar_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserProfile


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserProfileUpdate(BaseModel):
    full_name: str | None = None
    avatar_url: str | None = None

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            clean = v.strip()
            if len(clean) < 2:
                raise ValueError("El nombre debe tener al menos 2 caracteres")
            return clean
        return None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_pwd(cls, v: str) -> str:
        return validate_password_strength(v)


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean or not EMAIL_REGEX.match(clean):
            raise ValueError("El formato de correo electrónico no es válido")
        return clean


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_pwd(cls, v: str) -> str:
        return validate_password_strength(v)


class MessageResponse(BaseModel):
    message: str
