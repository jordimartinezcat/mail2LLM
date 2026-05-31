"""
Script de prueba para validar extracción de id_bcentral desde emails.
Simula un email con id_bcentral explícito y verifica que el LLM lo extrae correctamente.
"""

import logging
from config.loader import load_config
from llm.processor import extract_consumption
from db.repository import load_consorciat_cache

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)


def test_email_with_id_bcentral():
    """Test con email que incluye id_bcentral explícito."""
    
    # Email de ejemplo con id_bcentral
    email_body = """
Benvolguts,

Us informem dels consums d'aigua del mes d'abril de 2026:

Cliente: MESSER IBÉRICA DE GASES S.A.U - EL MORELL
ID Client: CL00091
Consum: 1.250,50 m³
Data: 30/04/2026

Cliente: CARBUROS METÁLICOS SA
Código: CL00234
Valor: 342,00 m³
Període: Abril 2026

Gràcies,
Consums Aigües Tarragona
"""
    
    # Cargar configuración
    config = load_config("config.xml")
    
    # Cargar cache de empresas para el prompt
    companies_cache = load_consorciat_cache(config.db)
    logger.info(f"Cache cargado: {len(companies_cache)} empresas")
    
    # Extraer consumos
    consumptions = extract_consumption(
        body=email_body,
        config=config.llm,
        email_date="Fri, 10 May 2026 12:00:00 +0000",
        sender="consums@aiguestarragona.cat",
        subject="Consums abril 2026",
        companies=companies_cache
    )
    
    if not consumptions:
        logger.error("❌ No se extrajeron consumos")
        return False
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Consumos extraídos: {len(consumptions)}")
    logger.info(f"{'='*60}\n")
    
    for i, c in enumerate(consumptions, 1):
        logger.info(f"Consumo #{i}:")
        logger.info(f"  - Empresa: {c.empresa}")
        logger.info(f"  - id_bcentral: {c.id_bcentral} {'✅ PRESENTE' if c.id_bcentral else '❌ AUSENTE'}")
        logger.info(f"  - Fecha: {c.fecha}")
        logger.info(f"  - Valor: {c.valor} {c.unidades}")
        logger.info("")
    
    # Validar que se extrajeron los ids
    ids_found = [c.id_bcentral for c in consumptions if c.id_bcentral]
    
    if len(ids_found) == 2:
        logger.info(f"✅ Test EXITOSO: Se extrajeron {len(ids_found)} id_bcentral correctamente")
        logger.info(f"   IDs extraídos: {ids_found}")
        return True
    else:
        logger.warning(f"⚠️  Test PARCIAL: Solo se extrajeron {len(ids_found)}/2 id_bcentral")
        logger.warning(f"   IDs extraídos: {ids_found}")
        return False


def test_email_without_id_bcentral():
    """Test con email SIN id_bcentral (debe usar fuzzy matching)."""
    
    email_body = """
Estimados,

Consumos de agua marzo 2026:

- MESSER EL MORELL: 890.25 m³
- CARBUROS METALICOS: 456.00 m³

Fecha: 31/03/2026

Saludos
"""
    
    config = load_config("config.xml")
    companies_cache = load_consorciat_cache(config.db)
    
    consumptions = extract_consumption(
        body=email_body,
        config=config.llm,
        email_date="Fri, 10 May 2026 12:00:00 +0000",
        sender="consums@aiguestarragona.cat",
        subject="Consums març 2026",
        companies=companies_cache
    )
    
    if not consumptions:
        logger.error("❌ No se extrajeron consumos")
        return False
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Test SIN id_bcentral (debe usar fuzzy matching)")
    logger.info(f"{'='*60}\n")
    
    for i, c in enumerate(consumptions, 1):
        logger.info(f"Consumo #{i}:")
        logger.info(f"  - Empresa: {c.empresa}")
        logger.info(f"  - id_bcentral: {c.id_bcentral or 'null (usará fuzzy matching)'}")
        logger.info(f"  - Valor: {c.valor} {c.unidades}")
        logger.info("")
    
    # Validar que NO hay ids (debe pasar a fuzzy matching)
    ids_found = [c.id_bcentral for c in consumptions if c.id_bcentral]
    
    if len(ids_found) == 0:
        logger.info(f"✅ Test EXITOSO: Sin id_bcentral → Se usará fuzzy matching en BD")
        return True
    else:
        logger.warning(f"⚠️  IDs extraídos inesperadamente: {ids_found}")
        return False


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("TEST 1: Email CON id_bcentral explícito")
    logger.info("="*60)
    test1 = test_email_with_id_bcentral()
    
    print("\n\n")
    
    logger.info("="*60)
    logger.info("TEST 2: Email SIN id_bcentral (fallback fuzzy matching)")
    logger.info("="*60)
    test2 = test_email_without_id_bcentral()
    
    print("\n\n")
    logger.info("="*60)
    logger.info("RESUMEN")
    logger.info("="*60)
    logger.info(f"Test 1 (con id_bcentral): {'✅ PASS' if test1 else '❌ FAIL'}")
    logger.info(f"Test 2 (sin id_bcentral): {'✅ PASS' if test2 else '❌ FAIL'}")
    logger.info("="*60)
