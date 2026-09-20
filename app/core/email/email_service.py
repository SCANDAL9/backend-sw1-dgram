"""
email_service.py — Servicio de envío de correos transaccionales (recuperación de contraseñas).
Soporta SMTP estándar y cuenta con fallback a logging estructurado e historial de pruebas para desarrollo.
"""
import smtplib
import asyncio
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Almacén de pruebas para verificar el envío en tests automatizados
_sent_emails_for_testing: list[dict] = []


class EmailService:
    @classmethod
    def get_test_sent_emails(cls) -> list[dict]:
        return _sent_emails_for_testing

    @classmethod
    def clear_test_sent_emails(cls) -> None:
        _sent_emails_for_testing.clear()

    @classmethod
    async def send_password_reset_email(cls, to_email: str, user_name: str, reset_token: str) -> bool:
        settings = get_settings()
        app_url = getattr(settings, "app_url", "http://localhost:4200")
        reset_link = f"{app_url}/reset-password?token={reset_token}"

        email_data = {
            "to": to_email,
            "user_name": user_name,
            "reset_token": reset_token,
            "reset_link": reset_link,
        }
        _sent_emails_for_testing.append(email_data)

        # Si no hay servidor SMTP configurado, usar fallback a log estructurado
        smtp_host = getattr(settings, "smtp_host", None)
        if not smtp_host:
            logger.info(
                "\n==================== [DEV EMAIL LOG] ====================\n"
                "Para: %s (%s)\n"
                "Asunto: Recuperación de contraseña — dgram\n"
                "Enlace de reseteo: %s\n"
                "Token: %s\n"
                "=========================================================",
                to_email,
                user_name,
                reset_link,
                reset_token,
            )
            return True

        # Envío asíncrono vía SMTP
        def _send_sync():
            try:
                smtp_port = getattr(settings, "smtp_port", 587)
                smtp_user = getattr(settings, "smtp_user", None)
                smtp_pass = getattr(settings, "smtp_password", None)
                smtp_from = getattr(settings, "smtp_from_email", "noreply@dgram.io")

                msg = MIMEMultipart("alternative")
                msg["Subject"] = "Recuperación de contraseña — dgram"
                msg["From"] = smtp_from
                msg["To"] = to_email

                text = f"Hola {user_name},\n\nPara restablecer tu contraseña en dgram, haz clic en el siguiente enlace:\n{reset_link}\n\nEste enlace expira en 15 minutos.\nSi no solicitaste este cambio, puedes ignorar este mensaje."
                html = f"""
                <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
                    <h2 style="color: #4f46e5;">dgram</h2>
                    <p>Hola <strong>{user_name}</strong>,</p>
                    <p>Recibimos una solicitud para restablecer la contraseña de tu cuenta.</p>
                    <div style="margin: 24px 0;">
                        <a href="{reset_link}" style="background-color: #4f46e5; color: white; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Restablecer mi contraseña</a>
                    </div>
                    <p style="font-size: 12px; color: #64748b;">Este enlace expira en 15 minutos. Si no solicitaste este cambio, puedes ignorar este correo de forma segura.</p>
                </div>
                """
                msg.attach(MIMEText(text, "plain"))
                msg.attach(MIMEText(html, "html"))

                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                return True
            except Exception as e:
                logger.error("Fallo al enviar correo SMTP a %s: %s", to_email, e)
                return False

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _send_sync)
