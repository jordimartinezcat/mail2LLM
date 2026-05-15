"""
Script de prueba para verificar la conexión a PostgreSQL.
Ejecutar desde el servidor donde está Apache NIFI.
"""

import sys
from config.loader import load_config
from db.repository import load_consorciat_cache

def main():
    print("=" * 70)
    print("TEST DE CONEXIÓN A POSTGRESQL")
    print("=" * 70)
    
    try:
        # Cargar configuración
        config = load_config()
        print(f"\n✓ Configuración cargada correctamente")
        print(f"  - BD habilitada: {config.db.enabled}")
        print(f"  - Host: {config.db.host}:{config.db.port}")
        print(f"  - Base de datos: {config.db.database}")
        print(f"  - Usuario: {config.db.username}")
        print(f"  - Tabla: ga_landing.ite_bcfact_clients")
        print(f"  - Campo nombre: {config.db.consorciat_name_field}")
        print(f"  - Match threshold: {config.db.match_threshold}")
        print(f"  - Client encoding: {config.db.client_encoding}")
        
        if not config.db.enabled:
            print("\n⚠ BD DESHABILITADA en config.xml")
            print("  Para habilitar: <enabled>true</enabled>")
            sys.exit(1)
        
        # Intentar cargar caché de empresas
        print(f"\n⏳ Conectando a PostgreSQL...")
        cache = load_consorciat_cache(config.db)
        
        print(f"\n✓ CONEXIÓN EXITOSA")
        print(f"  - Empresas cargadas: {len(cache)}")
        
        if cache:
            print(f"\n📋 Primeras 10 empresas:")
            for i, (number, alias) in enumerate(cache[:10], 1):
                print(f"  {i:2}. {number:10} | {alias}")
            
            if len(cache) > 10:
                print(f"  ... y {len(cache) - 10} más")
            
            # Buscar empresas específicas para prueba
            print(f"\n🔍 Buscando empresas específicas:")
            keywords = ["carburos", "messer", "cm"]
            for keyword in keywords:
                matches = [(n, a) for n, a in cache if keyword.lower() in a.lower()]
                if matches:
                    print(f"\n  Empresas con '{keyword}':")
                    for number, alias in matches[:5]:
                        print(f"    - {number:10} | {alias}")
                else:
                    print(f"\n  No se encontraron empresas con '{keyword}'")
        
        print(f"\n{'=' * 70}")
        print("✓ TEST COMPLETADO EXITOSAMENTE")
        print("=" * 70)
        
    except Exception as exc:
        print(f"\n❌ ERROR: {exc}")
        print(f"\n{'=' * 70}")
        print("✗ TEST FALLIDO")
        print("=" * 70)
        sys.exit(1)

if __name__ == "__main__":
    main()
