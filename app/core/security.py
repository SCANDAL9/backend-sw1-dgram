"""
app.core.security — Utilidades criptográficas, hashing de contraseñas y manejo de tokens JWT.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from app.core.config import get_settings


def _get_jwt_settings():
    settings = get_settings()
    return settings.jwt_secret_key, settings.jwt_expiration_seconds


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    if not hashed_password or "$" not in hashed_password:
        return False
    salt, key_hex = hashed_password.split("$", 1)
    key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return hmac.compare_digest(key.hex(), key_hex)


def create_jwt_token(payload: dict) -> str:
    secret_key, expiration_seconds = _get_jwt_settings()
    header = {"alg": "HS256", "typ": "JWT"}
    payload_copy = dict(payload)
    if "exp" not in payload_copy:
        payload_copy["exp"] = int(time.time()) + expiration_seconds

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    header_b64 = b64url(json.dumps(header).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload_copy).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}"
    sig = hmac.new(secret_key.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = b64url(sig)
    return f"{signing_input}.{sig_b64}"


def decode_jwt_token(token: str) -> dict | None:
    try:
        secret_key, _ = _get_jwt_settings()
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        def b64url_decode(s: str) -> bytes:
            rem = len(s) % 4
            if rem > 0:
                s += "=" * (4 - rem)
            return base64.urlsafe_b64decode(s)

        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256
        ).digest()

        actual_sig = b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload_bytes = b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        if "exp" in payload and payload["exp"] < int(time.time()):
            return None

        return payload
    except Exception:
        return None
