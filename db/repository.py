import difflib
import logging
import unicodedata
from datetime import datetime

import psycopg2

from config.loader import DBConfig

logger = logging.getLogger("processMail")

_TABLE_CONSUMS    = "ga_datalake.ite_consums_datarect"  # Tabla de pruebas
_TABLE_CONSORCIAT = "ga_landing.ite_bcfact_clients"
_TABLE_CONSORCIATS = "ga_landing.ite_consorciat"  # Relación id_bcentral → Id (sin 's')
_TABLE_COMPTADORS = "ga_landing.ite_comptadors"
_TABLE_TAGS       = "ga_landing.ite_consums_tags"
_TABLE_CONSUMS_DIA = "ga_landing.consums_dia"  # Tabla de consumos diarios
_COMENTARI = "Consum introduit des de correu electrònic"
_COMENTARI_SENSE_DATA = "Consum introduit des de correu electrònic. Data no indicada"
_TIPUS_CORREO = 3  # Tipo 3 = introducción desde correo

_INSERT = f"""
INSERT INTO {_TABLE_CONSUMS} (data, idtag, valor, tipus, descrip)
VALUES (%(data)s, %(idtag)s, %(valor)s, %(tipus)s, %(descrip)s)
"""

_INSERT_CONSUMS_DIA = f"""
INSERT INTO {_TABLE_CONSUMS_DIA} ("Id", "Data", "Consum", especial)
VALUES (%(id)s, %(data)s, %(consum)s, true)
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
    Carrega totes les empreses de ga_landing.ite_bcfact_clients.
    Retorna llista de (number, alias) filtrant files amb number o alias nuls.
    """
    query = (
        f"SELECT number, alias "
        f"FROM {_TABLE_CONSORCIAT} "
        f"WHERE number IS NOT NULL AND alias IS NOT NULL"
    )
    with _connect(config) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    logger.info(
        "Cache ite_bcfact_clients carregada: %d empreses (columna 'alias')",
        len(rows),
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


def _get_idtag_from_consorciat(id_consorciat: str, config: DBConfig) -> int | None:
    """
    Dado un id_consorciat (ej: CL00091), busca el idTag correspondiente:
    1. Busca en ite_consorciat donde id_bcentral = id_consorciat → obtiene Id
    2. Busca contador en ite_comptadors donde IdGC = Id, Pare IS NOT NULL, Baixa IS NULL
    3. Obtiene el campo IdMaximo del contador
    4. Transforma: quita "_" intermedios + añade sufijo "_CSM"
    5. Busca en ite_consums_tags donde tag = nombre transformado
    6. Retorna idTag
    
    Retorna None si no se encuentra.
    """
    with _connect(config) as conn:
        with conn.cursor() as cur:
            # 1. Buscar en ite_consorciat para obtener Id (integer)
            query_consorciat = f"""
                SELECT id
                FROM {_TABLE_CONSORCIATS}
                WHERE id_bcentral = %s
                LIMIT 1
            """
            cur.execute(query_consorciat, (id_consorciat,))
            row = cur.fetchone()
            
            if not row:
                logger.warning(
                    "No se encontró Id en ite_consorciat para id_bcentral '%s'",
                    id_consorciat
                )
                return None
            
            idgc = row[0]
            logger.debug("id_bcentral '%s' → Id=%s", id_consorciat, idgc)
            
            # 2. Buscar contador y obtener IdMaximo
            query_comptador = f"""
                SELECT "IdMaximo"
                FROM {_TABLE_COMPTADORS}
                WHERE "IdGC" = %s
                  AND "Pare" IS NOT NULL
                  AND "Baixa" IS NULL
                LIMIT 1
            """
            cur.execute(query_comptador, (idgc,))
            row = cur.fetchone()
            
            if not row:
                logger.warning(
                    "No se encontró contador para IdGC=%s (id_consorciat '%s', Pare NOT NULL, Baixa NULL)",
                    idgc, id_consorciat
                )
                return None
            
            id_maxim = row[0]
            logger.debug("Contador encontrado para IdGC=%s: IdMaximo=%s", idgc, id_maxim)
            
            # 3. Transformar IdMaximo al formato tag: XXXXX_XXX_XXX_CSM
            # Ejemplo: "12345123123" → "12345_123_123_CSM"
            if len(id_maxim) >= 11:
                tag_name = f"{id_maxim[:5]}_{id_maxim[5:8]}_{id_maxim[8:11]}_CSM"
            else:
                # Fallback: añadir solo "_CSM" si el formato no coincide
                tag_name = id_maxim + "_CSM"
            logger.debug("Tag buscado: %s → %s", id_maxim, tag_name)
            
            # 4. Buscar en ite_consums_tags
            query_tag = f"""
                SELECT "idTag"
                FROM {_TABLE_TAGS}
                WHERE tag = %s
                LIMIT 1
            """
            cur.execute(query_tag, (tag_name,))
            row = cur.fetchone()
            
            if not row:
                logger.warning(
                    "No se encontró tag '%s' en ite_consums_tags para id_consorciat '%s'",
                    tag_name, id_consorciat
                )
                return None
            
            idtag = row[0]
            logger.debug("idTag encontrado: %s → %s", tag_name, idtag)
            return idtag


def _get_contador_id_from_id_bcentral(id_bcentral: str, config: DBConfig) -> str | None:
    """
    Dado un id_bcentral (ej: CL00068), busca el Id del contador correspondiente para insertar en consums_dia.
    
    Flujo:
    1. Busca en ite_consorciat el Id (IdGC) correspondiente al id_bcentral
    2. Busca el contador en ite_comptadors donde IdGC coincida y Pare IS NOT NULL
    3. Retorna el "Id" del contador (ej: 'INPA', 'BAS', etc.)
    
    Retorna None si no se encuentra.
    """
    with _connect(config) as conn:
        with conn.cursor() as cur:
            # 1. Buscar en ite_consorciat para obtener el Id (IdGC)
            query_consorciat = f"""
                SELECT id
                FROM {_TABLE_CONSORCIATS}
                WHERE id_bcentral = %s
                LIMIT 1
            """
            cur.execute(query_consorciat, (id_bcentral,))
            row = cur.fetchone()
            
            if not row:
                logger.warning(
                    "No se encontró IdGC en ite_consorciat para id_bcentral='%s'",
                    id_bcentral
                )
                return None
            
            idgc = row[0]
            logger.debug("id_bcentral '%s' → IdGC=%s", id_bcentral, idgc)
            
            # 2. Buscar contador en ite_comptadors
            query_comptador = f"""
                SELECT "Id"
                FROM {_TABLE_COMPTADORS}
                WHERE "IdGC" = %s
                LIMIT 1
            """
            cur.execute(query_comptador, (idgc,))
            row = cur.fetchone()
            
            if not row:
                logger.warning(
                    "No se encontró contador en ite_comptadors para IdGC=%s (id_bcentral '%s')",
                    idgc, id_bcentral
                )
                return None
            
            contador_id = row[0]
            logger.debug("Contador encontrado: Id='%s' para IdGC=%s", contador_id, idgc)
            return contador_id
    
    return None


def save_consumptions(
    consumptions: list,
    config: DBConfig,
    cache: list[tuple[str, str]],
) -> tuple[int, list[str]]:
    """
    Insereix una llista de Consumption a ga_datalake.ite_consums_datarect.
    
    PRIORIDAD 1 (✨ NUEVO):
    - Si el consumo tiene 'idtag' (extraído del atributo data-tag del HTML):
      → Inserción DIRECTA sin búsquedas (más rápido y preciso)
    
    PRIORIDAD 2 (Fallback para emails antiguos):
    - Si no tiene 'idtag': Busca por id_bcentral o fuzzy matching
    - Cerca id_consorciat per similitud de text usant el cache en memòria
    - Busca idTag a través de ite_comptadors i ite_consums_tags
    
    Retorna (nombre de files inserides, llista d'empreses no identificades).
    """
    inserted = 0
    not_found: list[str] = []

    with _connect(config) as conn:
        with conn.cursor() as cur:
            for c in consumptions:
                idtag = None
                nom_empresa = c.empresa or "?"
                id_consorciat = None
                
                # ✨ PRIORIDAD 1: Usar idtag directamente si viene en el consumo (del atributo data-tag)
                if hasattr(c, 'idtag') and c.idtag is not None:
                    idtag = c.idtag
                    logger.info(
                        "  ✅ idTag directo desde HTML (data-tag): %s | Empresa: '%s' | Fecha: %s | Valor: %.2f %s",
                        idtag, nom_empresa, c.fecha, c.valor, c.unidades
                    )
                    # Inserción directa sin búsquedas
                    descrip = _COMENTARI_SENSE_DATA if getattr(c, "fecha_inferida", False) else _COMENTARI
                    try:
                        cur.execute(_INSERT, {
                            "data":    c.fecha,
                            "idtag":   idtag,
                            "valor":   float(c.valor),
                            "tipus":   _TIPUS_CORREO,
                            "descrip": descrip,
                        })
                        inserted += 1
                        logger.info("  ✅ Consumo insertado exitosamente (idTag=%s)", idtag)
                        
                        # ══════════════════════════════════════════════════════════════
                        # INSERCIÓN ADICIONAL en ga_landing.consums_dia
                        # ══════════════════════════════════════════════════════════════
                        if hasattr(c, 'id_bcentral') and c.id_bcentral:
                            contador_id = _get_contador_id_from_id_bcentral(c.id_bcentral, config)
                            if contador_id:
                                try:
                                    cur.execute(_INSERT_CONSUMS_DIA, {
                                        "id":     contador_id,
                                        "data":   c.fecha,
                                        "consum": int(c.valor),
                                    })
                                    logger.info("  ✅ Consumo insertado también en consums_dia (Id='%s')", contador_id)
                                except Exception as e_dia:
                                    logger.error(
                                        "  ❌ Error insertando en consums_dia para Id='%s': %s",
                                        contador_id, str(e_dia)
                                    )
                            else:
                                logger.warning(
                                    "  ⚠️  No se pudo obtener Id del contador para id_bcentral='%s' — sin inserción en consums_dia",
                                    c.id_bcentral
                                )
                        else:
                            logger.debug("  ℹ️  Sin id_bcentral — sin inserción en consums_dia")
                        
                    except Exception as e:
                        logger.error(
                            "  ❌ Error insertando consumo con idTag=%s: %s",
                            idtag, str(e)
                        )
                        not_found.append(f"{nom_empresa} (idTag={idtag})")
                    continue  # Siguiente consumo
                
                # ══════════════════════════════════════════════════════════════
                # PRIORIDAD 2 (Fallback): Búsqueda tradicional para emails sin formato CLxxxxx-idtag
                # ══════════════════════════════════════════════════════════════
                
                logger.info(
                    "  ⚠️  idTag no proporcionado en HTML — usando búsqueda tradicional para: '%s'",
                    nom_empresa
                )
                
                # PRIORIDAD 2.1: Usar id_bcentral si viene en el consumo extraído por el LLM
                if c.id_bcentral:
                    id_bcentral_str = c.id_bcentral.strip().upper()
                    logger.info(
                        "  Identificació per id_bcentral: '%s' (id=%s) — verificant...",
                        c.empresa, id_bcentral_str,
                    )
                    # 1) Verificar que existe en ite_bcfact_clients
                    query_verify = f"SELECT alias FROM {_TABLE_CONSORCIAT} WHERE number = %s LIMIT 1"
                    cur.execute(query_verify, (id_bcentral_str,))
                    row = cur.fetchone()
                    if row:
                        nom_empresa = row[0]  # Usar el nombre oficial de la BD
                        logger.info("  ✅ id_bcentral '%s' verificat a bcfact_clients → Empresa: '%s'", id_bcentral_str, nom_empresa)
                        
                        # ✅ FIX: Guardar el id_bcentral STRING, NO el Id numérico
                        # La función _get_idtag_from_consorciat() espera id_bcentral (STRING), no Id (INTEGER)
                        id_consorciat = id_bcentral_str  # Ejemplo: "CL00107"
                        logger.info("  ✅ id_bcentral establecido: %s", id_consorciat)
                    else:
                        logger.warning(
                            "  ⚠️  id_bcentral '%s' NO trobat a bcfact_clients — intentant fuzzy matching amb nom: '%s'",
                            id_bcentral_str, c.empresa
                        )
                        id_consorciat = None  # Forzar fallback
                
                # PRIORIDAD 2.2: Extraer ID del formato "NOMBRE (CL00123)" en el nombre de empresa
                if not id_consorciat and c.empresa:
                    import re
                    id_match = re.search(r'\(([^)]+)\)$', c.empresa)
                    if id_match:
                        id_consorciat = id_match.group(1).strip().upper()
                        nom_empresa = c.empresa[:id_match.start()].strip()
                        logger.info(
                            "  Identificació per format '(ID)': '%s' → id=%s",
                            nom_empresa, id_consorciat
                        )
                
                # PRIORIDAD 2.3 (Fallback): Fuzzy matching por nombre
                if not id_consorciat and c.empresa:
                    logger.info(
                        "  Intentant fuzzy matching per nom: '%s' (threshold=%.2f)",
                        c.empresa, config.match_threshold
                    )
                    match = _find_best_match(c.empresa, cache, config.match_threshold)
                    if match is None:
                        # Intentar con nombre simplificado (quitar "desde R.Materials", etc.)
                        simplified_name = re.sub(r'\s+(desde|from|de)\s+.*$', '', c.empresa, flags=re.IGNORECASE).strip()
                        if simplified_name != c.empresa:
                            logger.info(
                                "  Reintentant amb nom simplificat: '%s'",
                                simplified_name
                            )
                            match = _find_best_match(simplified_name, cache, config.match_threshold)
                        
                        if match is None:
                            logger.warning(
                                "❌ Empresa no identificada: '%s' (llindar=%.2f) — consum omès (data=%s, valor=%s)",
                                c.empresa, config.match_threshold, c.fecha, c.valor,
                            )
                            not_found.append(c.empresa or "?")
                            continue
                    
                    id_consorciat, nom_trobat, score = match
                    nom_empresa = nom_trobat
                    logger.info(
                        "  ✅ Identificació per fuzzy matching: '%s' → '%s' (id=%s, score=%.2f)",
                        c.empresa, nom_trobat, id_consorciat, score,
                    )

                # Buscar idTag a través de ite_comptadors → ite_consums_tags
                idtag = _get_idtag_from_consorciat(id_consorciat, config)
                if idtag is None:
                    logger.warning(
                        "No se pudo obtener idTag para '%s' (id=%s) — consum omès",
                        nom_empresa, id_consorciat
                    )
                    not_found.append(c.empresa or "?")
                    continue

                logger.info(
                    "  Guardando consumo → %s (%s, idTag=%s) | %s | %.2f %s",
                    nom_empresa, id_consorciat, idtag, c.fecha, c.valor, c.unidades
                )

                descrip = _COMENTARI_SENSE_DATA if getattr(c, "fecha_inferida", False) else _COMENTARI

                cur.execute(_INSERT, {
                    "data":    c.fecha,
                    "idtag":   idtag,
                    "valor":   float(c.valor),  # La tabla usa numeric(18,6)
                    "tipus":   _TIPUS_CORREO,   # 3 = introducción desde correo
                    "descrip": descrip,
                })
                inserted += 1
                
                # ══════════════════════════════════════════════════════════════
                # INSERCIÓN ADICIONAL en ga_landing.consums_dia
                # ══════════════════════════════════════════════════════════════
                if id_consorciat:  # Tenemos id_bcentral del fallback
                    contador_id = _get_contador_id_from_id_bcentral(id_consorciat, config)
                    if contador_id:
                        try:
                            cur.execute(_INSERT_CONSUMS_DIA, {
                                "id":     contador_id,
                                "data":   c.fecha,
                                "consum": int(c.valor),
                            })
                            logger.info("  ✅ Consumo insertado también en consums_dia (Id='%s')", contador_id)
                        except Exception as e_dia:
                            logger.error(
                                "  ❌ Error insertando en consums_dia para Id='%s': %s",
                                contador_id, str(e_dia)
                            )
                    else:
                        logger.warning(
                            "  ⚠️  No se pudo obtener Id del contador para id_consorciat='%s' — sin inserción en consums_dia",
                            id_consorciat
                        )
                else:
                    logger.debug("  ℹ️  Sin id_consorciat — sin inserción en consums_dia")

        conn.commit()

    if inserted:
        logger.info("Insertat(s) %d consum(s) a %s", inserted, _TABLE_CONSUMS)
    if not_found:
        logger.warning(
            "%d consum(s) omès(os) per empresa no identificada o sense idTag: %s",
            len(not_found), ", ".join(not_found),
        )

    return inserted, not_found
