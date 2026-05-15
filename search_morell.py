"""
Script para buscar empresas con "MORELL" en el nombre.
"""

from config.loader import load_config
from db.repository import load_consorciat_cache

def main():
    config = load_config()
    cache = load_consorciat_cache(config.db)
    
    print("\n🔍 Empresas con 'MORELL' en el nombre:")
    print("=" * 80)
    
    found = []
    for id_, nom in cache:
        if 'MORELL' in nom.upper():
            found.append((id_, nom))
    
    if found:
        for id_, nom in found:
            print(f"  {id_:10} | {nom}")
    else:
        print("  No se encontraron empresas con 'MORELL' en el nombre")
    
    print("=" * 80)
    print(f"Total encontradas: {len(found)}")

if __name__ == "__main__":
    main()
