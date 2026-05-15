import logging
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _extract_email_address(sender: str) -> str:
    """
    Extrae la dirección de email de un string de remitente.
    Ejemplos:
      "John Doe <john@example.com>" → "john@example.com"
      "john@example.com" → "john@example.com"
    """
    match = re.search(r'<([^>]+)>', sender)
    if match:
        return match.group(1).strip().lower()
    return sender.strip().lower()


def _smtp_connect(nc, config_email, logger: logging.Logger) -> smtplib.SMTP:
    """
    Abre y autentica una conexión SMTP.
    - Si oauth2_client_id está configurado en <email>: usa OAuth2 XOAUTH2 (Outlook/Hotmail)
    - Si no: usa login básico usuario/contraseña
    """
    if nc.smtp_tls:
        smtp = smtplib.SMTP(nc.smtp_server, nc.smtp_port, timeout=30)
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
    else:
        smtp = smtplib.SMTP_SSL(nc.smtp_server, nc.smtp_port, timeout=30)

    # Autenticación OAuth2 si hay client_id configurado en <email>
    if getattr(config_email, "oauth2_client_id", ""):
        from email_io.oauth2 import get_smtp_oauth2_string
        xoauth2 = get_smtp_oauth2_string(
            username=nc.smtp_user,
            client_id=config_email.oauth2_client_id,
            token_cache_path=getattr(config_email, "oauth2_token_cache", "token_cache.json"),
        )
        code, _ = smtp.docmd("AUTH", f"XOAUTH2 {xoauth2}")
        if code != 235:
            raise smtplib.SMTPAuthenticationError(code, b"XOAUTH2 failed")
        logger.debug("SMTP autenticado con OAuth2 XOAUTH2")
    elif nc.smtp_user and nc.smtp_password:
        smtp.login(nc.smtp_user, nc.smtp_password)

    return smtp


def send_error_notification(
    failed_messages: list[dict],
    config,
    logger: logging.Logger,
) -> None:
    """
    Envía notificaciones de error:
    - A los destinatarios principales (<to>): TODOS los errores
    - A cada remitente en include_original_senders: SOLO sus propios errores
    """
    nc = config.notifications
    if not nc.enabled:
        return
    if not failed_messages:
        return
    if not nc.to_addrs:
        logger.warning("Notificaciones habilitadas pero sin destinatarios configurados (<to>)")
        return

    # 1. Enviar TODOS los errores a los destinatarios principales
    _send_error_email(
        failed_messages=failed_messages,
        recipients=nc.to_addrs,
        config=config,
        logger=logger,
        subject_suffix="revisión necesaria"
    )
    
    # 2. Agrupar mensajes por remitente para envíos individuales
    messages_by_sender = {}
    for m in failed_messages:
        sender_email = _extract_email_address(m.get("sender", ""))
        if sender_email and sender_email in nc.include_original_senders:
            if sender_email not in messages_by_sender:
                messages_by_sender[sender_email] = []
            messages_by_sender[sender_email].append(m)
    
    # 3. Enviar a cada remitente SOLO sus errores
    for sender_email, sender_messages in messages_by_sender.items():
        _send_error_email(
            failed_messages=sender_messages,
            recipients=[sender_email],
            config=config,
            logger=logger,
            subject_suffix="tu correo requiere revisión"
        )
        logger.info("Notificación enviada a remitente original: %s (%d mensaje(s))", 
                   sender_email, len(sender_messages))


def _send_error_email(
    failed_messages: list[dict],
    recipients: list[str],
    config,
    logger: logging.Logger,
    subject_suffix: str,
) -> None:
    """Helper para enviar un correo de error con mensajes adjuntos."""
    nc = config.notifications
    n = len(failed_messages)

    # ── Cuerpo del correo ─────────────────────────────────────────────────────
    lines = [
        f"processMail ha finalizado con {n} correo(s) pendiente(s) de revisión.",
        "",
        "Detalle de errores:",
        "",
    ]
    for i, m in enumerate(failed_messages, 1):
        lines.append(
            f"  {i}. [{m['uid']}] {m['subject'] or '(sin asunto)'}"
            f" | De: {m['sender'] or '?'}"
            f" | Fecha: {m['date'] or '?'}"
        )
        lines.append(f"     Motivo: {m['reason']}")
        lines.append("")
    lines.append("Los correos originales se adjuntan como ficheros de texto.")
    body_text = "\n".join(lines)

    # ── Construir mensaje MIME ────────────────────────────────────────────────
    msg = MIMEMultipart()
    msg["Subject"] = f"[processMail] {n} correo(s) con error — {subject_suffix}"
    msg["From"] = nc.from_addr
    msg["To"] = ", ".join(recipients)
    
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # ── Adjuntar cada correo fallido como .eml (formato Outlook) ──────────────
    for m in failed_messages:
        subject_safe = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in (m["subject"] or "sin_asunto")
        )[:50].strip()
        filename = f"error_{m['uid']}_{subject_safe}.eml"
        
        # Usar el mensaje RAW completo si está disponible
        raw_content = m.get("raw", "")
        if raw_content:
            # Añadir comentario al inicio con el motivo del error (como headers)
            eml_content = (
                f"X-ProcessMail-Error: {m['reason']}\r\n"
                f"X-ProcessMail-UID: {m['uid']}\r\n"
                f"{raw_content}"
            )
        else:
            # Construir un .eml básico si no hay raw
            from email.utils import formatdate
            eml_content = (
                f"From: {m['sender'] or 'unknown@unknown'}\r\n"
                f"To: consums@ccaait.cat\r\n"
                f"Subject: {m['subject'] or '(sin asunto)'}\r\n"
                f"Date: {m['date'] or formatdate()}\r\n"
                f"X-ProcessMail-Error: {m['reason']}\r\n"
                f"X-ProcessMail-UID: {m['uid']}\r\n"
                f"Content-Type: text/plain; charset=utf-8\r\n"
                f"\r\n"
                f"{m['body'] or '(sin cuerpo)'}"
            )
        
        # Adjuntar como application/octet-stream con extensión .eml
        part = MIMEBase("application", "octet-stream")
        # Codificar el contenido a bytes UTF-8
        part.set_payload(eml_content.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    # ── Enviar ────────────────────────────────────────────────────────────────
    try:
        with _smtp_connect(nc, config.email, logger) as smtp:
            smtp.sendmail(nc.from_addr, recipients, msg.as_string())

        logger.info(
            "Notificación de error enviada a: %s (%d adjunto(s))",
            ", ".join(recipients),
            n,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo enviar la notificación de error: %s", exc)


def send_confirmation_request(
    uid: str,
    original_sender: str,
    original_subject: str,
    consumptions: list,
    config,
    logger: logging.Logger,
) -> None:
    """
    Envia un correu HTML sol·licitant confirmació per inserir consums a BD.
    Permet confirmació total (TOTS) o selectiva (per números de línia).
    
    Args:
        uid: UID del missatge original
        original_sender: Remitent del missatge amb consums
        original_subject: Assumpte del missatge original
        consumptions: Llista d'objectes Consumption extrets
        config: Configuració completa (email + notifications)
        logger: Logger
    """
    nc = config.notifications
    if not nc.enabled:
        logger.warning("No es pot enviar confirmació: notificacions deshabilitades")
        return
    if not nc.to_addrs:
        logger.warning("No es pot enviar confirmació: sense destinataris configurats")
        return
    
    # ── Construir taula HTML de consums ────────────────────────────────────────
    consumptions_rows = ""
    for i, c in enumerate(consumptions, 1):
        consumptions_rows += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{i}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{c.fecha}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{c.empresa}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{c.valor} {c.unidades}</td>
        </tr>"""
    
    # ── Cos HTML del correu ───────────────────────────────────────────────────
    body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 800px; margin: 20px auto; padding: 20px; background: #f9f9f9; border-radius: 8px; }}
        .header {{ background: #2E75B6; color: white; padding: 15px; border-radius: 5px; }}
        .info-box {{ background: white; padding: 15px; margin: 15px 0; border-left: 4px solid #2E75B6; }}
        table {{ width: 100%; border-collapse: collapse; background: white; margin: 15px 0; }}
        th {{ background: #2E75B6; color: white; padding: 10px; text-align: left; }}
        .actions {{ background: #fff3cd; padding: 15px; margin: 20px 0; border-radius: 5px; border: 2px solid #ffc107; }}
        .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>✉️ Confirmació Requerida - Consums Detectats</h2>
        </div>
        
        <div class="info-box">
            <p><strong>S'han extret {len(consumptions)} consum(s) del següent correu:</strong></p>
            <ul>
                <li><strong>Remitent:</strong> {original_sender}</li>
                <li><strong>Assumpte:</strong> {original_subject}</li>
                <li><strong>UID:</strong> {uid}</li>
            </ul>
        </div>
        
        <h3>📊 Consums detectats:</h3>
        <table>
            <thead>
                <tr>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">#</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Data</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Empresa</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Consum</th>
                </tr>
            </thead>
            <tbody>
                {consumptions_rows}
            </tbody>
        </table>
        
        <div class="actions">
            <h3>⚠️ Acció Requerida</h3>
            <p><strong>Per CONFIRMAR la inserció a la base de dades</strong>, respon aquest correu amb una de les següents paraules:</p>
            <p style="text-align: center; font-size: 18px; margin: 15px 0;">
                <strong>OK</strong> | <strong>CONFIRMAR</strong> | <strong>SÍ</strong> | <strong>ACEPTAR</strong>
            </p>
            <p style="font-size: 13px; color: #666; margin-top: 15px;">
                <em>Nota: També pots confirmar consums específics responent amb <strong>CONFIRMAR 1,3,5</strong> (números de línia)</em>
            </p>
            <p style="margin-top: 10px;">Per <strong>REBUTJAR</strong>, simplement ignora aquest missatge.</p>
        </div>
        
        <div class="footer">
            <p style="color: #999; font-size: 11px;">ID de confirmació: {uid}</p>
            <p>Aquest és un missatge automàtic del sistema mail2LLM</p>
        </div>
    </div>
</body>
</html>
"""
    
    # ── Versió text pla (fallback) ────────────────────────────────────────────
    body_text = f"""
S'han extret {len(consumptions)} consum(s) del següent correu:

  Remitent: {original_sender}
  Assumpte: {original_subject}
  UID: {uid}

Consums detectats:

"""
    for i, c in enumerate(consumptions, 1):
        body_text += f"  {i}. Data: {c.fecha} | Empresa: {c.empresa} | Valor: {c.valor} {c.unidades}\n"
    
    body_text += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Per CONFIRMAR la inserció a la base de dades, respon aquest correu
amb una de les següents opcions:

  • CONFIRMAR TOTS (confirma tots els consums)
  • CONFIRMAR 1,3,5 (confirma només les línies especificades)
  • OK / SÍ / ACEPTAR (confirma tots)

Per REBUTJAR, simplement ignora aquest missatge.

(ID de confirmació: {uid})
"""
    
    # ── Construir missatge MIME amb HTML + text ───────────────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[CONFIRMACIÓ #{uid}] Consums: {original_subject}"
    msg["From"] = nc.from_addr
    msg["To"] = ", ".join(nc.to_addrs)
    
    # Incluir remitente original en CC si está configurado
    cc_addrs = []
    sender_email = _extract_email_address(original_sender)
    if sender_email and sender_email in nc.include_original_senders:
        cc_addrs.append(sender_email)
        msg["Cc"] = sender_email
        logger.debug("Incluyendo en CC al remitente original: %s", sender_email)
    
    # Adjuntar ambdues versions (text pla primer, HTML després)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    
    # ── Enviar ────────────────────────────────────────────────────────────────
    try:
        with _smtp_connect(nc, config.email, logger) as smtp:
            all_recipients = nc.to_addrs + cc_addrs
            smtp.sendmail(nc.from_addr, all_recipients, msg.as_string())
        
        logger.info(
            "Sol·licitud de confirmació HTML enviada a: %s (UID: %s, %d consum(s))",
            ", ".join(nc.to_addrs),
            uid,
            len(consumptions),
        )
        if cc_addrs:
            logger.info("  CC incluido: %s", sender_email)
    except Exception as exc:  # noqa: BLE001
        logger.error("No s'ha pogut enviar la sol·licitud de confirmació: %s", exc)
