"""
Script para probar el fuzzy matching con el nombre extraído por el LLM.
"""

from config.loader import load_config
from db.repository import load_consorciat_cache
import difflib
import unicodedata

def _normalize(text: str) -> str:
    """Minúscules, sense accents, sense espais redundants."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.split())

def main():
    config = load_config()
    cache = load_consorciat_cache(config.db)
    
    # Simular lo que extrajo el LLM
    empresa_llm = "MORELL"
    
    print(f"\n🔍 Buscando coincidencias para: '{empresa_llm}'")
    print(f"   Normalizado: '{_normalize(empresa_llm)}'")
    print("=" * 80)
    
    # Buscar todas las coincidencias y mostrar scores
    empresa_norm = _normalize(empresa_llm)
    matches = []
    
    for id_, nom in cache:
        score = difflib.SequenceMatcher(None, empresa_norm, _normalize(nom)).ratio()
        matches.append((score, id_, nom))
    
    # Ordenar por score (descendente)
    matches.sort(reverse=True)
    
    print(f"\n📊 Top 10 coincidencias:")
    print("-" * 80)
    for i, (score, id_, nom) in enumerate(matches[:10], 1):
        print(f"{i:2}. {score*100:5.1f}% | {id_:10} | {nom}")
    
    print("\n" + "=" * 80)
    best_score, best_id, best_nom = matches[0]
    print(f"✓ MEJOR COINCIDENCIA: '{best_nom}' (ID: {best_id}, {best_score*100:.1f}%)")
    print(f"  Threshold configurado: {config.db.match_threshold * 100:.0f}%")
    
    if best_score >= config.db.match_threshold:
        print(f"  ✓ Supera el threshold → ACEPTADO")
    else:
        print(f"  ✗ No supera el threshold → RECHAZADO")

if __name__ == "__main__":
    main()
