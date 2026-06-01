"""
Test con el email real de MESSER para validar el nuevo prompt.
"""

import logging
from config.loader import load_config
from llm.processor import extract_consumption
from db.repository import load_consorciat_cache

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)


# Email real copiado del buzón
REAL_EMAIL_BODY = """
ATENCIÓ: Aquest correu electrònic s'ha enviat des de fora de l'organització. No cliqueu enllaços ni obriu arxius adjunts a menys que reconegueu al remitent i sapigueu que el contingut és segur.


Muchas gracias, saludos
Yolanda

De: consums@ccaait.cat <consums@ccaait.cat>
Enviado el: lunes, 1 de junio de 2026 0:22
Para: Gutierrez, Yolanda <Yolanda.Gutierrez@messergroup.com>
Asunto: Consums mensuals Maig 2026 - MESSER IBÉRICA DE GASES S.A.

No suele recibir correo electrónico de consums@ccaait.cat. Por qué es esto importante
[CAUTION] This email originated from outside of the organization. Do not click links or open attachments unless you recognize the sender and know the content is safe.
Sol·licitud mensual de consums
[Consorci d'Aigües de Tarragona]

Benvolgut/da,

Mitjançant aquest correu, es sol·licita l'enviament dels consums corresponents al període indicat a continuació.
Període:  Maig 2026

📝 Com respondre:

Premeu "Respondre a aquest correu" i ompliu les cel·les resaltades en groc de la columna "Consum" amb els vostres valors.
Id
Nom d'empresa
Consum comptador
CL00501
MESSER MORELL desde R.Materials
1093780

Us agrairíem que féssiu arribar aquesta informació el més aviat possible.

Atentament,

Consorci d'Aigües de Tarragona



Consums CAT



Instal·lacions Centrals



Bústia autònoma de consums del CAT



Autovia T11 Km14, 43006 Tarragona



ITE



Tel. 977546410  /  Fax 977546240



Tel. 977636254



cat@ccaait.cat  /  www.ccaait.cat



consums@ccaait.cat




La informació continguda en aquest correu electrònic és confidencial i s'adreça exclusivament al seu destinatari. La seva divulgació està prohibida. En cas d'haver-lo rebut per equivocació, els demanem que el destrueixin i ens ho comuniquin. Gràcies per la seva col·laboració.

Pel medi ambient, val la pena imprimir aquest correu?
"""


def test_real_email():
    """Test con el email real de MESSER."""
    
    config = load_config("config.xml")
    
    # Cargar cache de empresas
    companies_cache = load_consorciat_cache(config.db)
    logger.info(f"Cache cargado: {len(companies_cache)} empresas")
    
    # Extraer consumos
    consumptions = extract_consumption(
        body=REAL_EMAIL_BODY,
        config=config.llm,
        email_date="Mon, 1 Jun 2026 06:27:50 +0000",
        sender="Yolanda.Gutierrez@messergroup.com",
        subject="RE: Consums mensuals Maig 2026 - MESSER IBÉRICA DE GASES S.A.",
        companies=companies_cache
    )
    
    if not consumptions:
        logger.error("❌ No se extrajeron consumos")
        return False
    
    print("\n" + "="*80)
    print("RESULTADO DE EXTRACCIÓN")
    print("="*80)
    
    for i, c in enumerate(consumptions, 1):
        print(f"\nConsumo #{i}:")
        print(f"  fecha:       {c.fecha}")
        print(f"  empresa:     {c.empresa}")
        print(f"  id_bcentral: {c.id_bcentral}")
        print(f"  valor:       {c.valor}")
        print(f"  unidades:    {c.unidades}")
    
    print("\n" + "="*80)
    
    # Validación
    expected_id = "CL00501"
    expected_valor = 1093780
    expected_fecha = "2026-05-31"  # Último día de mayo 2026
    
    if len(consumptions) != 1:
        logger.error(f"❌ Se esperaba 1 consumo, se encontraron {len(consumptions)}")
        return False
    
    c = consumptions[0]
    
    checks = [
        (c.id_bcentral == expected_id, f"id_bcentral: {c.id_bcentral} == {expected_id}"),
        (c.valor == expected_valor, f"valor: {c.valor} == {expected_valor}"),
        (c.fecha == expected_fecha, f"fecha: {c.fecha} == {expected_fecha}"),
        (c.empresa is not None and "MESSER" in c.empresa.upper(), f"empresa contiene MESSER: {c.empresa}"),
        (c.unidades == "m3", f"unidades: {c.unidades} == m3"),
        ("Consorci" not in (c.empresa or ""), f"NO extrae 'Consorci': {c.empresa}")
    ]
    
    all_passed = True
    print("\nVALIDACIÓN:")
    print("-" * 80)
    for passed, desc in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {desc}")
        if not passed:
            all_passed = False
    
    print("-" * 80)
    
    if all_passed:
        print("\n🎉 Test EXITOSO - Todos los checks pasaron")
        return True
    else:
        print("\n⚠️  Test FALLIDO - Algunos checks no pasaron")
        return False


if __name__ == "__main__":
    test_real_email()
