"""
Gestión de consumos pendientes de confirmación.
Los consumos se guardan en JSON hasta recibir confirmación por email.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("processMail")

PENDING_FILE = Path("pending_confirmations.json")


def save_pending(uid: str, msg_data: dict, consumptions: list[Any]) -> None:
    """
    Guarda consumos pendientes de confirmación.
    
    Args:
        uid: UID del mensaje original
        msg_data: Datos del mensaje (subject, sender, date, body)
        consumptions: Lista de objetos Consumption extraídos
    """
    pending = _load_pending_data()
    
    pending[uid] = {
        "subject": msg_data["subject"],
        "sender": msg_data["sender"],
        "date": msg_data["date"],
        "body": msg_data["body"],
        "timestamp": datetime.now().isoformat(),
        "consumptions": [
            {
                "fecha": c.fecha,
                "empresa": c.empresa,
                "valor": c.valor,
                "unidades": c.unidades,
            }
            for c in consumptions
        ],
    }
    
    _save_pending_data(pending)
    logger.info("Consumos del mensaje [%s] guardados como pendientes de confirmación", uid)


def get_pending(uid: str) -> dict | None:
    """
    Obtiene consumos pendientes para un UID específico.
    
    Returns:
        Dict con datos del mensaje y consumos, o None si no existe
    """
    pending = _load_pending_data()
    return pending.get(uid)


def confirm_and_remove(uid: str) -> list[dict] | None:
    """
    Marca tots els consums com a confirmats i els elimina de pendents.
    
    Returns:
        Llista de consumptions dict, o None si el UID no existeix
    """
    return confirm_and_remove_selective(uid, None)


def confirm_and_remove_selective(uid: str, line_numbers: list[int] | None = None) -> list[dict] | None:
    """
    Confirma consums selectius o tots (si line_numbers és None).
    
    Args:
        uid: UID del missatge original
        line_numbers: Llista de números de línia a confirmar (1-indexed), o None per tots
    
    Returns:
        Llista de consumptions confirmats, o None si el UID no existeix
    """
    pending = _load_pending_data()
    
    if uid not in pending:
        return None
    
    data = pending[uid]
    all_consumptions = data["consumptions"]
    
    # Si no hi ha números especificats, confirmar TOTS
    if line_numbers is None:
        pending.pop(uid)
        _save_pending_data(pending)
        logger.info("TOTS els consums del missatge [%s] confirmats i eliminats de pendents", uid)
        return all_consumptions
    
    # Confirmació selectiva
    confirmed = []
    remaining = []
    
    for i, consumption in enumerate(all_consumptions, 1):
        if i in line_numbers:
            confirmed.append(consumption)
        else:
            remaining.append(consumption)
    
    # Si queden consums pendents, actualitzar; si no, eliminar entrada
    if remaining:
        data["consumptions"] = remaining
        pending[uid] = data
        logger.info(
            "Consums selectius del missatge [%s] confirmats: %d de %d (queden %d pendents)",
            uid, len(confirmed), len(all_consumptions), len(remaining)
        )
    else:
        pending.pop(uid)
        logger.info(
            "Tots els consums del missatge [%s] han estat confirmats (últims %d)",
            uid, len(confirmed)
        )
    
    _save_pending_data(pending)
    return confirmed


def list_pending() -> dict[str, dict]:
    """Retorna todos los consumos pendientes."""
    return _load_pending_data()


def _load_pending_data() -> dict:
    """Carga el archivo JSON de pendientes."""
    if not PENDING_FILE.exists():
        return {}
    
    try:
        with PENDING_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Error al cargar pending_confirmations.json: %s", e)
        return {}


def _save_pending_data(data: dict) -> None:
    """Guarda el archivo JSON de pendientes."""
    try:
        with PENDING_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error("Error al guardar pending_confirmations.json: %s", e)
