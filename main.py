import sys

from config.loader import load_config
from db.repository import load_consorciat_cache, save_consumptions
from email_io.notifier import send_error_notification
from email_io.reader import EmailReader
from llm.processor import Consumption, extract_consumption
from logger_setup import setup_logger


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

                if not msg["body"]:
                    logger.warning("Mensaje [%s] sin cuerpo de texto, omitido", uid)
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": "(sin cuerpo de texto)",
                        "reason": "Sin cuerpo de texto",
                    })
                    errors += 1
                    continue

                consumptions = extract_consumption(msg["body"], config.llm, msg["date"])

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
                    reader.mark_as_unread(uid)
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
                    reader.mark_as_unread(uid)
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
                        "Mensaje [%s] con %d registro(s) incompleto(s) — se deja en origen y se marca no leído",
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
                    reader.mark_as_unread(uid)
                    errors += 1
                    continue

                for c in consumptions:
                    logger.info(
                        "  Consumo extraído → fecha=%s | empresa=%s | valor=%s %s",
                        c.fecha, c.empresa, c.valor, c.unidades,
                    )

                # Mover mensaje a carpeta de procesados (solo si todos los registros están completos)
                # y si la BD no rechaza ningún consumo por empresa no identificada
                db_not_found: list[str] = []
                if config.db.enabled:
                    try:
                        _, db_not_found = save_consumptions(consumptions, config.db, consorciat_cache)
                    except Exception as db_exc:  # noqa: BLE001
                        logger.error("Error al guardar en BD el mensaje [%s]: %s", uid, db_exc)

                if db_not_found:
                    logger.warning(
                        "Mensaje [%s] con %d empresa(s) no identificada(s) en BD: %s — "
                        "se deja en origen para revisión manual",
                        uid, len(db_not_found), ", ".join(db_not_found),
                    )
                    failed_messages.append({
                        "uid": uid,
                        "subject": msg["subject"],
                        "sender": msg["sender"],
                        "date": msg.get("date", ""),
                        "body": msg["body"],
                        "reason": (
                            f"Empresa(s) no identificada(s) en BD: {', '.join(db_not_found)}"
                        ),
                    })
                    reader.mark_as_unread(uid)
                    errors += 1
                    continue

                reader.move_message(uid, config.email.processed_folder)

                results.extend(consumptions)
                processed += 1

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
