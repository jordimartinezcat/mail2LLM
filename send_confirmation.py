"""
Script para enviar respuesta de confirmación "OK".
Simula la respuesta del administrador confirmando la inserción.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.loader import load_config
from email_io.oauth2 import get_smtp_oauth2_string


def send_confirmation_reply():
    """Envía una respuesta "OK" para confirmar la inserción."""
    config = load_config()
    
    # Cuerpo de la respuesta
    body = """OK

(ID de confirmación: 127)

--- Respuesta automática de confirmación ---
"""
    
    # Crear mensaje MIME
    msg = MIMEMultipart()
    msg["From"] = config.notifications.to_addrs[0]  # jmartinez@ccaait.cat
    msg["To"] = config.email.username  # consums@ccaait.cat
    msg["Subject"] = "RE: [CONFIRMACIÓN REQUERIDA] Consumos detectados: Consumo de agua - Abril 2026 - TEST"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    # Conectar a SMTP con OAuth2
    print(f"Conectando a {config.notifications.smtp_server}:{config.notifications.smtp_port}...")
    
    if config.notifications.smtp_tls:
        smtp = smtplib.SMTP(config.notifications.smtp_server, config.notifications.smtp_port, timeout=30)
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
    else:
        smtp = smtplib.SMTP_SSL(config.notifications.smtp_server, config.notifications.smtp_port, timeout=30)
    
    # Autenticar con OAuth2
    print("Autenticando con OAuth2...")
    xoauth2 = get_smtp_oauth2_string(
        username=config.email.username,
        client_id=config.email.oauth2_client_id,
        token_cache_path=config.email.oauth2_token_cache,
    )
    code, response = smtp.docmd("AUTH", f"XOAUTH2 {xoauth2}")
    if code != 235:
        raise smtplib.SMTPAuthenticationError(code, response)
    
    # Enviar correo
    print(f"Enviando confirmación a {config.email.username}...")
    smtp.sendmail(
        msg["From"],
        [config.email.username],
        msg.as_string()
    )
    smtp.quit()
    
    print("✅ Respuesta de confirmación enviada correctamente")
    print(f"   De: {msg['From']}")
    print(f"   Para: {config.email.username}")
    print(f"   Asunto: {msg['Subject']}")
    print(f"   Contenido: OK (UID: 127)")
    print("\nEl correo debería aparecer en la bandeja en unos segundos.")


if __name__ == "__main__":
    send_confirmation_reply()
