import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


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
    """Envía un correo de notificación con los mensajes con error adjuntos como .txt."""
    nc = config.notifications
    if not nc.enabled:
        return
    if not failed_messages:
        return
    if not nc.to_addrs:
        logger.warning("Notificaciones habilitadas pero sin destinatarios configurados (<to>)")
        return

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
    msg["Subject"] = f"[processMail] {n} correo(s) con error — revisión necesaria"
    msg["From"] = nc.from_addr
    msg["To"] = ", ".join(nc.to_addrs)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # ── Adjuntar cada correo fallido como .txt ────────────────────────────────
    for m in failed_messages:
        subject_safe = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in (m["subject"] or "sin_asunto")
        )[:50].strip()
        filename = f"error_{m['uid']}_{subject_safe}.txt"
        content = (
            f"UID    : {m['uid']}\n"
            f"Asunto : {m['subject'] or '(sin asunto)'}\n"
            f"De     : {m['sender'] or '?'}\n"
            f"Fecha  : {m['date'] or '?'}\n"
            f"Motivo : {m['reason']}\n"
            f"{'=' * 60}\n\n"
            f"{m['body'] or '(sin cuerpo)'}"
        )
        part = MIMEBase("application", "octet-stream")
        part.set_payload(content.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    # ── Enviar ────────────────────────────────────────────────────────────────
    try:
        with _smtp_connect(nc, config.email, logger) as smtp:
            smtp.sendmail(nc.from_addr, nc.to_addrs, msg.as_string())

        logger.info(
            "Notificación de error enviada a: %s (%d adjunto(s))",
            ", ".join(nc.to_addrs),
            n,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo enviar la notificación de error: %s", exc)
