import re
import sys

from config.loader import load_config
from db.repository import load_consorciat_cache, save_consumptions
from email_io.notifier import send_confirmation_request, send_error_notification
from email_io.reader import EmailReader
from llm.processor import Consumption, extract_consumption
from logger_setup import setup_logger
from pending_confirmations import confirm_and_remove, save_pending


def _is_confirmation_message(body: str, subject: str) -> bool:
    """
    Detecta si un missatge és una resposta de confirmació.
    Busca paraules clau com: OK, CONFIRMAR, SÍ, SI, ACEPTAR, TOTS
    """
    if not body:
        return False
    
    text = (body + " " + (subject or "")).upper()
    keywords = [
        r'\bOK\b',
        r'\bCONFIRMAR\b',
        r'\bSÍ\b',
        r'\bSI\b',
        r'\bACEPTAR\b',
        r'\bCONFIRMO\b',
        r'\bACEPTO\b',
        r'\bTOTS\b',
        r'\bTODOS\b',
    ]
    
    return any(re.search(pattern, text) for pattern in keywords)


def _extract_confirmation_uid(body: str, raw: str = "", subject: str = "") -> str | None:
    """
    Extreu el UID de confirmació del subject, body o missatge raw.
    Busca patró: 
      - En subject: [CONFIRMACIÓ #135]
      - En body/raw: (ID de confirmació: 135)
    
    Args:
        body: Cos de text pla del missatge
        raw: Missatge raw complet (opcional, per buscar en parts citades)
        subject: Assumpte del missatge (prioritari)
    
    Returns:
        UID com a string, o None si no es troba
    """
    # PRIORITAT 1: Buscar en el subject (més fiable)
    if subject:
        # Patró: [CONFIRMACIÓ #135] o RE: [CONFIRMACIÓ #135]
        match = re.search(r'\[CONFIRMACI[ÓO]\s+#(\d+)\]', subject, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # PRIORITAT 2: Buscar en el body
    if body:
        match = re.search(r'\(ID de confirmaci[óo]:\s*(\d+)\)', body, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # PRIORITAT 3: Buscar en el missatge raw complet
    if raw:
        match = re.search(r'\(ID de confirmaci[óo]:\s*(\d+)\)', raw, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def main() -> None:
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("processMail iniciado")

    # Cargar configuración
    try:
        config = load_config()
        logger.info(
            "Configuración cargada: servidor=%s, carpeta=%s, modelo=%s",
            config.email.server,
            config.email.folder,
            config.llm.model,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Error en la configuración: %s", exc)
        sys.exit(1)

    # Carregar cache d'empreses de la BD (una sola query per tota l'execució)
    consorciat_cache: list = []
    if config.db.enabled:
        try:
            consorciat_cache = load_consorciat_cache(config.db)
        except Exception as db_exc:  # noqa: BLE001
            logger.error("No s'ha pogut connectar a la BD per carregar les empreses: %s", db_exc)
            sys.exit(1)

    # Descargar y procesar correos
    try:
        with EmailReader(config.email) as reader:
            processed = 0
            errors = 0
            results = []
            failed_messages: list[dict] = []

            for uid, msg in reader.fetch_new_messages():
                logger.info(
                    "--- Procesando mensaje [%s] | Asunto: '%s' | De: %s",
                    uid,
                    msg["subject"],
                    msg["sender"],
                )

                # Validar que tenga contenido (cuerpo o PDFs adjuntos)
                pdf_contents = msg.get("pdf_contents", [])
                has_content = bool(msg["body"]) or bool(pdf_contents)
                
                if not has_content:
                    logger.warning("Mensaje [%s] sin cuerpo de texto ni PDFs adjuntos, omitido", uid)
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": "(sin contenido)",
                        "reason": "Sin cuerpo de texto ni PDFs adjuntos",
                    })
                    reader.move_message(uid, config.email.folder_errors)
                    errors += 1
                    continue

                # ═══════════════════════════════════════════════════════════════
                # DETECTAR SI ÉS UNA CONFIRMACIÓ
                # ═══════════════════════════════════════════════════════════════
                if _is_confirmation_message(msg["body"], msg["subject"]):
                    logger.info("Missatge [%s] detectat com a CONFIRMACIÓ", uid)
                    
                    # Buscar UID original: primer en subject, després en body/raw
                    original_uid = _extract_confirmation_uid(
                        msg["body"], 
                        msg.get("raw", ""),
                        msg["subject"]
                    )
                    
                    if not original_uid:
                        logger.warning(
                            "Confirmació [%s] sense UID vàlid — mogut a errors",
                            uid,
                        )
                        failed_messages.append({
                            "uid": uid,
                            "subject": msg["subject"],
                            "sender": msg["sender"],
                            "date": msg.get("date", ""),
                            "body": msg["body"],
                            "reason": "Confirmació sense UID de referència",
                        })
                        reader.move_message(uid, config.email.folder_errors)
                        errors += 1
                        continue
                    
                    # Detectar si és confirmació selectiva (CONFIRMAR 1,3,5) o total (TOTS)
                    # Buscar solo en las primeras líneas del body (antes del texto citado)
                    body_lines = msg["body"].split("\n")
                    first_lines = "\n".join(body_lines[:10]).upper()  # Primeras 10 líneas
                    text = first_lines + " " + (msg["subject"] or "").upper()
                    line_numbers = None
                    
                    logger.debug("Analizando confirmación - Primeras líneas: %s", first_lines[:200])
                    
                    # Buscar patró: "CONFIRMAR 1,3,5" o "1,2" o "1 2 3"
                    # Primero buscar "CONFIRMAR" seguido de números
                    match = re.search(r'CONFIRMAR\s+([\d,\s]+?)(?:\s|$)', text)
                    if match:
                        logger.debug("Match encontrado con 'CONFIRMAR': %s", match.group(1))
                    
                    if not match:
                        # Si no hay "CONFIRMAR", buscar línea que comience con números y comas
                        # Más flexible: acepta línea que empiece con dígitos
                        match = re.search(r'^\s*([\d,\s]+?)\s*$', first_lines, re.MULTILINE)
                        if match:
                            logger.debug("Match encontrado (solo números): %s", match.group(1))
                    
                    if match and "TOTS" not in text and "TODOS" not in text and "OK" not in text:
                        # Extreure números (separats per comes o espais)
                        numbers_str = match.group(1).replace(" ", ",").strip(",")
                        try:
                            line_numbers = [int(n.strip()) for n in numbers_str.split(",") if n.strip() and n.strip().isdigit()]
                            if line_numbers:  # Solo si hay números válidos
                                logger.info("Confirmació SELECTIVA: línies %s", line_numbers)
                            else:
                                logger.warning("Números extrets però buits, assumint confirmació total")
                        except ValueError:
                            logger.warning("Format de números invàlid: %s, assumint confirmació total", numbers_str)
                    
                    if not line_numbers:
                        if "TOTS" in text or "TODOS" in text or "OK" in text or "SÍ" in text or "SI" in text or "ACEPTAR" in text:
                            logger.info("Confirmació TOTAL (paraula clau detectada)")
                        else:
                            logger.warning("No s'ha detectat confirmació selectiva ni total clara - assumint TOTAL per defecte")
                    
                    # Recuperar consums pendents (totals o selectius)
                    from pending_confirmations import confirm_and_remove_selective
                    consumptions_data = confirm_and_remove_selective(original_uid, line_numbers)
                    
                    if not consumptions_data:
                        logger.warning(
                            "Confirmación [%s] para UID [%s] que no tiene consumos pendientes",
                            uid,
                            original_uid,
                        )
                        failed_messages.append({
                            "uid": uid,
                            "subject": msg["subject"],
                            "sender": msg["sender"],
                            "date": msg.get("date", ""),
                            "body": msg["body"],
                            "reason": f"Sin consumos pendientes para UID {original_uid}",
                        })
                        reader.move_message(uid, config.email.folder_errors)
                        errors += 1
                        continue
                    
                    # Reconstruir objetos Consumption
                    consumptions = [
                        Consumption(
                            fecha=c["fecha"],
                            empresa=c["empresa"],
                            valor=c["valor"],
                            unidades=c["unidades"],
                        )
                        for c in consumptions_data
                    ]
                    
                    logger.info(
                        "Confirmación [%s] → Insertando %d consumo(s) del mensaje original [%s]",
                        uid,
                        len(consumptions),
                        original_uid,
                    )
                    
                    # Insertar en BD
                    db_not_found: list[str] = []
                    if config.db.enabled:
                        try:
                            _, db_not_found = save_consumptions(
                                consumptions, config.db, consorciat_cache
                            )
                        except Exception as db_exc:  # noqa: BLE001
                            logger.error(
                                "Error al guardar en BD los consumos confirmados [%s]: %s",
                                uid,
                                db_exc,
                            )
                            failed_messages.append({
                                "uid": uid,
                                "subject": msg["subject"],
                                "sender": msg["sender"],
                                "date": msg.get("date", ""),
                                "body": msg["body"],
                                "reason": f"Error BD: {db_exc}",
                            })
                            reader.move_message(uid, config.email.folder_errors)
                            errors += 1
                            continue
                    
                    if db_not_found:
                        logger.warning(
                            "Confirmación [%s] con %d empresa(s) no identificada(s): %s",
                            uid,
                            len(db_not_found),
                            ", ".join(db_not_found),
                        )
                        failed_messages.append({
                            "uid": uid,
                            "subject": msg["subject"],
                            "sender": msg["sender"],
                            "date": msg.get("date", ""),
                            "body": msg["body"],
                            "reason": f"Empresa(s) no identificada(s): {', '.join(db_not_found)}",
                        })
                        reader.move_message(uid, config.email.folder_errors)
                        errors += 1
                        continue
                    
                    # Mover confirmación a carpeta de confirmaciones OK
                    reader.move_message(uid, config.email.folder_confirmed)
                    results.extend(consumptions)
                    processed += 1
                    
                    logger.info(
                        "✓ Consumos confirmados e insertados en BD (mensaje original [%s])",
                        original_uid,
                    )
                    continue

                # ═══════════════════════════════════════════════════════════════
                # MENSAJE NORMAL: EXTRAER CONSUMOS (email + PDFs)
                # ═══════════════════════════════════════════════════════════════
                pdf_contents = msg.get("pdf_contents", [])
                if pdf_contents:
                    logger.info("Mensaje [%s] con %d PDF(s) adjunto(s)", uid, len(pdf_contents))
                
                consumptions = extract_consumption(
                    msg["body"], 
                    config.llm, 
                    msg["date"],
                    pdf_contents=pdf_contents
                )

                if consumptions is None:
                    logger.error(
                        "No se pudo extraer el consumo del mensaje [%s]", uid
                    )
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": msg["body"],
                        "reason": "Error al llamar al LLM o respuesta no parseable",
                    })
                    reader.move_message(uid, config.email.folder_errors)
                    errors += 1
                    continue

                if not consumptions:
                    logger.warning(
                        "Mensaje [%s] sin datos de consumo — De: %s | Cuerpo:\n%s",
                        uid,
                        msg["sender"],
                        msg["body"],
                    )
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": msg["body"],
                        "reason": "Sin datos de consumo detectados",
                    })
                    reader.move_message(uid, config.email.folder_errors)
                    errors += 1
                    continue

                # Verificar que todos los registros tienen los campos completos
                incompletos = [
                    c for c in consumptions
                    if not c.fecha or not c.empresa or c.valor is None
                ]
                if incompletos:
                    for c in incompletos:
                        logger.warning(
                            "  Registro incompleto en [%s] → fecha=%s | empresa=%s | valor=%s",
                            uid, c.fecha, c.empresa, c.valor,
                        )
                    logger.warning(
                        "Mensaje [%s] con %d registro(s) incompleto(s) — movido a errores",
                        uid, len(incompletos),
                    )
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": msg["body"],
                        "reason": (
                            f"{len(incompletos)} registro(s) incompleto(s): "
                            + "; ".join(
                                f"fecha={c.fecha} empresa={c.empresa} valor={c.valor}"
                                for c in incompletos
                            )
                        ),
                    })
                    reader.move_message(uid, config.email.folder_errors)
                    errors += 1
                    continue

                for c in consumptions:
                    logger.info(
                        "  Consumo extraído → fecha=%s | empresa=%s | valor=%s %s",
                        c.fecha, c.empresa, c.valor, c.unidades,
                    )

                # ═══════════════════════════════════════════════════════════════
                # GUARDAR COMO PENDIENTE Y ENVIAR CONFIRMACIÓN
                # ═══════════════════════════════════════════════════════════════
                try:
                    save_pending(uid, msg, consumptions)
                    send_confirmation_request(
                        uid=uid,
                        original_sender=msg["sender"],
                        original_subject=msg["subject"],
                        consumptions=consumptions,
                        config=config,
                        logger=logger,
                    )
                    
                    # Mover mensaje a carpeta de procesados
                    reader.move_message(uid, config.email.folder_processed)
                    processed += 1
                    
                    logger.info(
                        "✓ Consumos guardados como pendientes — confirmación enviada (UID: %s)",
                        uid,
                    )
                    
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Error al guardar pendientes o enviar confirmación [%s]: %s",
                        uid,
                        exc,
                    )
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": msg["body"],
                        "reason": f"Error al procesar: {exc}",
                    })
                    reader.move_message(uid, config.email.folder_errors)
                    errors += 1

            logger.info(
                "Ejecución finalizada — procesados: %d | errores: %d",
                processed,
                errors,
            )

    except Exception as exc:  # noqa: BLE001
        logger.error("Error inesperado durante la lectura de correos: %s", exc)
        sys.exit(1)

    logger.info("processMail finalizado")
    logger.info("=" * 60)

    # Resumen ordenado por fecha y empresa (fuera del bloque IMAP para evitar mezcla con logs)
    if results:
        results.sort(key=lambda c: (c.fecha or "", c.empresa or ""))
        col_fecha   = max(len("Fecha"),   max(len(c.fecha   or "-") for c in results))
        col_empresa = max(len("Empresa"), max(len(c.empresa or "-") for c in results))
        col_valor   = max(len("Valor (m3)"), max(len(str(c.valor) if c.valor is not None else "-") for c in results))
        sep = f"+{'-' * (col_fecha + 2)}+{'-' * (col_empresa + 2)}+{'-' * (col_valor + 2)}+"
        header = f"| {'Fecha':<{col_fecha}} | {'Empresa':<{col_empresa}} | {'Valor (m3)':>{col_valor}} |"
        print("\n" + sep)
        print(header)
        print(sep)
        for c in results:
            fecha   = c.fecha   or "-"
            empresa = c.empresa or "-"
            valor   = str(c.valor) if c.valor is not None else "-"
            print(f"| {fecha:<{col_fecha}} | {empresa:<{col_empresa}} | {valor:>{col_valor}} |")
        print(sep + "\n")

    # Notificación de errores (si hay correos fallidos y está habilitado)
    send_error_notification(failed_messages, config, logger)


if __name__ == "__main__":
    main()
