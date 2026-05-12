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
    Marca consumos como confirmados y los elimina de pendientes.
    
    Returns:
        Lista de consumptions dict, o None si el UID no existe
    """
    pending = _load_pending_data()
    
    if uid not in pending:
        return None
    
    data = pending.pop(uid)
    _save_pending_data(pending)
    
    logger.info("Consumos del mensaje [%s] confirmados y eliminados de pendientes", uid)
    return data["consumptions"]


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
