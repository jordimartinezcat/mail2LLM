"""
Script para enviar un correo de prueba con datos de consumo de agua.
Usa OAuth2 para autenticar con Outlook.
Soporta formato texto plano y HTML.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.loader import load_config
from email_io.oauth2 import get_smtp_oauth2_string


def send_test_email(html=False):
    """Envía un email de prueba con consumos de agua.
    
    Args:
        html: Si True, envía en formato HTML. Si False, en texto plano.
    """
    config = load_config()
    
    if html:
        # ── Versión HTML ──────────────────────────────────────────────────────
        body_html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .header { background: #2E75B6; color: white; padding: 15px; border-radius: 5px; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th { background: #2E75B6; color: white; padding: 10px; text-align: left; }
        td { padding: 8px; border: 1px solid #ddd; }
        .footer { color: #666; font-size: 12px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="header">
        <h2>📊 Informe de Consumo de Agua - Abril 2026</h2>
    </div>
    
    <p>Estimado equipo,</p>
    
    <p>Les informo sobre los <strong>consumos de agua</strong> del mes de <strong>abril de 2026</strong>:</p>
    
    <table>
        <thead>
            <tr>
                <th>Empresa</th>
                <th>Consumo (m³)</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>ACME Industrias SA</td>
                <td style="text-align: right;">1.250,50</td>
            </tr>
            <tr>
                <td>Beta Solutions</td>
                <td style="text-align: right;">342,00</td>
            </tr>
            <tr>
                <td>Gamma Tech Ltd</td>
                <td style="text-align: right;">875,25</td>
            </tr>
        </tbody>
    </table>
    
    <p><strong>Fecha de referencia:</strong> 30/04/2026</p>
    
    <div class="footer">
        <p>Por favor, procesen estos datos a la mayor brevedad.</p>
        <p>Saludos cordiales,<br>Sistema automático de facturación</p>
    </div>
</body>
</html>
"""
        # Versión texto plano (fallback)
        body_text = """
Estimado equipo,

Les informo sobre los consumos de agua del mes de abril de 2026:

┌─────────────────────────┬──────────────┐
│ Empresa                 │ Consumo (m³) │
├─────────────────────────┼──────────────┤
│ ACME Industrias SA      │    1.250,50  │
│ Beta Solutions          │      342,00  │
│ Gamma Tech Ltd          │      875,25  │
└─────────────────────────┴──────────────┘

Fecha de referencia: 30/04/2026

Por favor, procesen estos datos a la mayor brevedad.

Saludos cordiales,
Sistema automático de facturación
"""
        
        # Crear mensaje MIME con HTML + texto
        msg = MIMEMultipart("alternative")
        msg["From"] = config.email.username
        msg["To"] = config.email.username
        msg["Subject"] = "Consumo de agua - Abril 2026 - TEST HTML"
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        
    else:
        # ── Versión texto plano ───────────────────────────────────────────────
        body = """
Estimado equipo,

Les informo sobre los consumos de agua del mes de abril de 2026:

┌─────────────────────────┬──────────────┐
│ Empresa                 │ Consumo (m³) │
├─────────────────────────┼──────────────┤
│ ACME Industrias SA      │    1.250,50  │
│ Beta Solutions          │      342,00  │
│ Gamma Tech Ltd          │      875,25  │
└─────────────────────────┴──────────────┘

Fecha de referencia: 30/04/2026

Por favor, procesen estos datos a la mayor brevedad.

Saludos cordiales,
Sistema automático de facturación
"""
        
        # Crear mensaje MIME simple
        msg = MIMEMultipart()
        msg["From"] = config.email.username
        msg["To"] = config.email.username
        msg["Subject"] = "Consumo de agua - Abril 2026 - TEST"
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
    print(f"Enviando correo a {config.email.username}...")
    smtp.sendmail(
        config.email.username,
        [config.email.username],
        msg.as_string()
    )
    smtp.quit()
    
    formato = "HTML + texto" if html else "texto plano"
    print(f"✅ Correo de prueba enviado correctamente ({formato})")
    print(f"   De: {config.email.username}")
    print(f"   Para: {config.email.username}")
    print(f"   Asunto: {msg['Subject']}")
    print("\nEl correo debería aparecer en tu bandeja de entrada en unos segundos.")


if __name__ == "__main__":
    import sys
    
    # Por defecto HTML, o texto si se pasa --text
    html_mode = "--text" not in sys.argv
    
    if html_mode:
        print("📧 Enviando email en formato HTML...")
    else:
        print("📧 Enviando email en formato texto plano...")
    
    send_test_email(html=html_mode)
