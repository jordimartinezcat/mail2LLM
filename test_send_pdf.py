"""
Script para enviar un correo de prueba con PDF adjunto.
Usa OAuth2 para autenticar con Outlook.
"""
import io
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from config.loader import load_config
from email_io.oauth2 import get_smtp_oauth2_string


def create_test_pdf() -> bytes:
    """Crea un PDF de prueba con datos de consumo de agua."""
    buffer = io.BytesIO()
    
    # Crear PDF con reportlab
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Título
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, height - 100, "INFORME DE CONSUMO DE AGUA")
    c.drawString(100, height - 120, "Mayo 2026")
    
    # Contenido
    c.setFont("Helvetica", 12)
    y = height - 160
    
    c.drawString(100, y, "Estimado equipo,")
    y -= 30
    
    c.drawString(100, y, "A continuación se detallan los consumos de agua del mes de mayo de 2026:")
    y -= 40
    
    # Tabla de consumos
    c.setFont("Helvetica-Bold", 11)
    c.drawString(100, y, "EMPRESA")
    c.drawString(350, y, "CONSUMO (m³)")
    y -= 5
    c.line(100, y, 500, y)
    y -= 20
    
    c.setFont("Helvetica", 10)
    consumos = [
        ("Delta Corp International", "2.450,75"),
        ("Epsilon Manufacturing", "589,30"),
        ("Zeta Industries", "1.123,00"),
        ("Theta Services Ltd", "745,50"),
    ]
    
    for empresa, valor in consumos:
        c.drawString(100, y, empresa)
        c.drawString(350, y, valor)
        y -= 20
    
    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(100, y, "Fecha de referencia: 31/05/2026")
    
    y -= 40
    c.setFont("Helvetica-Italic", 9)
    c.drawString(100, y, "Por favor, procesen estos datos a la mayor brevedad.")
    y -= 20
    c.drawString(100, y, "Saludos cordiales,")
    y -= 15
    c.drawString(100, y, "Sistema automático de facturación")
    
    c.save()
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def send_test_email_with_pdf():
    """Envía un email de prueba con PDF adjunto."""
    config = load_config()
    
    # Cuerpo del email (simple)
    body_text = """Estimado equipo,

Adjunto el informe de consumos de agua del mes de mayo de 2026 en formato PDF.

Por favor, revisen el documento adjunto y procedan con el registro de los datos.

Saludos cordiales,
Sistema de Facturación
"""
    
    # Crear mensaje MIME
    msg = MIMEMultipart()
    msg["From"] = config.email.username
    msg["To"] = config.email.username
    msg["Subject"] = "Consumos de agua - Mayo 2026 - PDF ADJUNTO"
    
    # Adjuntar cuerpo de texto
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    
    # Crear y adjuntar PDF
    print("📄 Generando PDF de prueba...")
    pdf_data = create_test_pdf()
    
    pdf_attachment = MIMEApplication(pdf_data, _subtype="pdf")
    pdf_attachment.add_header("Content-Disposition", "attachment", filename="consumos_mayo_2026.pdf")
    msg.attach(pdf_attachment)
    
    # Conectar a SMTP con OAuth2
    print(f"📧 Conectando a {config.notifications.smtp_server}:{config.notifications.smtp_port}...")
    
    if config.notifications.smtp_tls:
        smtp = smtplib.SMTP(config.notifications.smtp_server, config.notifications.smtp_port, timeout=30)
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
    else:
        smtp = smtplib.SMTP_SSL(config.notifications.smtp_server, config.notifications.smtp_port, timeout=30)
    
    # Autenticar con OAuth2
    print("🔐 Autenticando con OAuth2...")
    xoauth2 = get_smtp_oauth2_string(
        username=config.email.username,
        client_id=config.email.oauth2_client_id,
        token_cache_path=config.email.oauth2_token_cache,
    )
    code, _ = smtp.docmd("AUTH", f"XOAUTH2 {xoauth2}")
    if code != 235:
        raise Exception(f"XOAUTH2 authentication failed: {code}")
    
    # Enviar correo
    print(f"📤 Enviando correo a {config.email.username}...")
    smtp.sendmail(config.email.username, [config.email.username], msg.as_string())
    smtp.quit()
    
    print("✅ Correo con PDF adjunto enviado correctamente")
    print(f"   De: {config.email.username}")
    print(f"   Para: {config.email.username}")
    print(f"   Asunto: Consumos de agua - Mayo 2026 - PDF ADJUNTO")
    print(f"   Adjunto: consumos_mayo_2026.pdf ({len(pdf_data)} bytes)")
    print()
    print("El correo debería aparecer en tu bandeja de entrada en unos segundos.")


if __name__ == "__main__":
    print("📧 Enviando email de prueba con PDF adjunto...")
    print()
    send_test_email_with_pdf()
