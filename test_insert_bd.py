"""
Script de prueba para simular inserción en BD sin procesar correos.
Usa los datos del pending_confirmations.json (UID 427).
"""

from config.loader import load_config
from db.repository import load_consorciat_cache, save_consumptions
from llm.processor import Consumption
from logger_setup import setup_logger

def main():
    logger = setup_logger()
    
    # Cargar configuración
    config = load_config()
    logger.info("=" * 80)
    logger.info("TEST DE INSERCIÓN EN BD")
    logger.info("=" * 80)
    
    # Cargar caché de empresas
    cache = load_consorciat_cache(config.db)
    
    # Datos de prueba del mensaje 427 (REPSOL PETROLEO y DOW)
    # Estos consumos ya vienen normalizados con formato "NOMBRE (ID)"
    test_consumptions = [
        Consumption(
            fecha="2026-05-01",  # Cambiada para evitar duplicados
            empresa="REPSOL FUELS (CL00091)",  # Ya normalizado
            valor=17340.0,
            unidades="m3"
        ),
        Consumption(
            fecha="2026-05-01",  # Cambiada para evitar duplicados
            empresa="DOW (CL00107)",  # Ya normalizado
            valor=403120.0,
            unidades="m3"
        ),
    ]
    
    logger.info("\n📦 Consumos a insertar:")
    for c in test_consumptions:
        logger.info("  - %s | %s | %.2f %s", c.empresa, c.fecha, c.valor, c.unidades)
    
    # Intentar guardar en BD
    logger.info("\n🔄 Iniciando inserción en BD...")
    try:
        inserted, not_found = save_consumptions(
            test_consumptions,
            config.db,
            cache
        )
        
        logger.info("\n" + "=" * 80)
        if inserted > 0:
            logger.info("✅ ÉXITO: %d consumo(s) insertado(s)", inserted)
        else:
            logger.warning("⚠️ No se insertaron consumos")
        
        if not_found:
            logger.error("❌ Empresas no identificadas: %s", ", ".join(not_found))
        
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error("\n" + "=" * 80)
        logger.error("❌ ERROR: %s", e)
        logger.error("=" * 80)
        raise

if __name__ == "__main__":
    main()
