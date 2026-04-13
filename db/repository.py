import difflib
import logging
import unicodedata
from datetime import datetime

import psycopg2

from config.loader import DBConfig

logger = logging.getLogger("processMail")

_TABLE_CONSUMS    = "ga_datalake.ite_consums_datarect"
_TABLE_CONSORCIAT = "ga_landing.ite_consorciat"
_COMENTARI = "Consum introduit des de correu electrònic"
_COMENTARI_SENSE_DATA = "Consum introduit des de correu electrònic. Data no indicada"

_INSERT = f"""
INSERT INTO {_TABLE_CONSUMS} (data, id_consorciat, valor, data_insercio, comentari)
VALUES (%(data)s, %(id_consorciat)s, %(valor)s, %(data_insercio)s, %(comentari)s)
"""


def _connect(config: DBConfig):
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.username,
        password=config.password,
        connect_timeout=10,
        # Encoding via options s'aplica durant el handshake inicial,
        # evitant errors de decodificació fins i tot en missatges d'error del servidor
        options=f"-c client_encoding={config.client_encoding}",
    )


def _normalize(text: str) -> str:
    """Minúscules, sense accents, sense espais redundants."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.split())


def load_consorciat_cache(config: DBConfig) -> list[tuple[str, str]]:
    """
    Carrega totes les empreses de ga_landing.ite_consorciat.
    Retorna llista de (id, nom) filtrant files amb id o nom nuls.
    """
    query = (
        f"SELECT id, {config.consorciat_name_field} "
        f"FROM {_TABLE_CONSORCIAT} "
        f"WHERE id IS NOT NULL AND {config.consorciat_name_field} IS NOT NULL"
    )
    with _connect(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    logger.info(
        "Cache ite_consorciat carregada: %d empreses (columna '%s')",
        len(rows), config.consorciat_name_field,
    )
    return rows


def _find_best_match(
    empresa: str,
    cache: list[tuple[str, str]],
    threshold: float,
) -> tuple[str, str, float] | None:
    """
    Cerca la millor coincidència per similitud de text (difflib).
    Normalitza ambdues cadenes (minúscules, sense accents) abans de comparar.
    Retorna (id, nom_original, score) si supera el llindar, o None.
    """
    empresa_norm = _normalize(empresa)
    best_score = 0.0
    best_id: str | None = None
    best_nom: str | None = None

    for id_, nom in cache:
        score = difflib.SequenceMatcher(None, empresa_norm, _normalize(nom)).ratio()
        if score > best_score:
            best_score = score
            best_id = id_
            best_nom = nom

    if best_score >= threshold:
        return best_id, best_nom, best_score
    return None


def save_consumptions(
    consumptions: list,
    config: DBConfig,
    cache: list[tuple[str, str]],
) -> tuple[int, list[str]]:
    """
    Insereix una llista de Consumption a ga_datalake.ite_consums_datarect.
    - Cerca id_consorciat per similitud de text usant el cache en memòria.
    - valor és int8: s'arrodoneix i s'avisa si hi havia decimals.
    - Si fecha_inferida=True, afegeix 'Data no indicada' al comentari.
    - Retorna (nombre de files inserides, llista d'empreses no identificades).
    """
    now = datetime.now()
    inserted = 0
    not_found: list[str] = []

    with _connect(config) as conn:
        with conn.cursor() as cur:
            for c in consumptions:
                match = _find_best_match(c.empresa, cache, config.match_threshold)
                if match is None:
                    logger.warning(
                        "Empresa no identificada: '%s' (llindar=%.2f) — consum omès (data=%s, valor=%s)",
                        c.empresa, config.match_threshold, c.fecha, c.valor,
                    )
                    not_found.append(c.empresa or "?")
                    continue

                id_consorciat, nom_trobat, score = match
                logger.info(
                    "  Empresa '%s' → '%s' (id=%s, score=%.2f)",
                    c.empresa, nom_trobat, id_consorciat, score,
                )

                valor_int = round(float(c.valor))
                comentari = _COMENTARI_SENSE_DATA if getattr(c, "fecha_inferida", False) else _COMENTARI

                cur.execute(_INSERT, {
                    "data":          c.fecha,
                    "id_consorciat": id_consorciat,
                    "valor":         valor_int,
                    "data_insercio": now,
                    "comentari":     comentari,
                })
                inserted += 1

        conn.commit()

    if inserted:
        logger.info("Insertat(s) %d consum(s) a %s", inserted, _TABLE_CONSUMS)
    if not_found:
        logger.warning(
            "%d consum(s) omès(os) per empresa no identificada: %s",
            len(not_found), ", ".join(not_found),
        )

    return inserted, not_found
