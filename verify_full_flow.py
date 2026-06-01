"""
Verificar flujo completo: CL00094 → Id → IdMaximo → Tag → idTag
"""

import psycopg2
from config.loader import load_config

config = load_config("config.xml")

conn = psycopg2.connect(
    host=config.db.host,
    port=config.db.port,
    dbname=config.db.database,
    user=config.db.username,
    password=config.db.password,
    options=f"-c client_encoding={config.db.client_encoding}",
)

try:
    with conn.cursor() as cur:
        id_bcentral = "CL00094"
        
        print("\n" + "="*80)
        print(f"FLUJO COMPLETO PARA {id_bcentral}")
        print("="*80)
        
        # Paso 1: bcfact_clients
        print(f"\n1️⃣ Buscar en ite_bcfact_clients...")
        cur.execute("SELECT number, alias FROM ga_landing.ite_bcfact_clients WHERE number = %s", (id_bcentral,))
        row = cur.fetchone()
        if row:
            print(f"   ✅ Encontrado: {row[0]} - {row[1]}")
        else:
            print(f"   ❌ NO encontrado")
            exit(1)
        
        # Paso 2: ite_consorciat
        print(f"\n2️⃣ Buscar Id en ite_consorciat (id_bcentral = {id_bcentral})...")
        cur.execute("SELECT id FROM ga_landing.ite_consorciat WHERE id_bcentral = %s", (id_bcentral,))
        row = cur.fetchone()
        if row:
            idgc = row[0]
            print(f"   ✅ Id encontrado: {idgc}")
        else:
            print(f"   ❌ NO encontrado en ite_consorciat")
            exit(1)
        
        # Paso 3: ite_comptadors
        print(f"\n3️⃣ Buscar contador en ite_comptadors (IdGC = {idgc}, Pare NOT NULL, Baixa NULL)...")
        cur.execute("""
            SELECT "IdMaximo"
            FROM ga_landing.ite_comptadors
            WHERE "IdGC" = %s
              AND "Pare" IS NOT NULL
              AND "Baixa" IS NULL
            LIMIT 1
        """, (idgc,))
        row = cur.fetchone()
        if row:
            id_maxim = row[0]
            print(f"   ✅ IdMaximo encontrado: {id_maxim}")
        else:
            print(f"   ❌ NO encontrado contador con Pare NOT NULL y Baixa NULL")
            # Buscar si hay contadores sin esas condiciones
            cur.execute('SELECT "IdMaximo", "Pare", "Baixa" FROM ga_landing.ite_comptadors WHERE "IdGC" = %s LIMIT 5', (idgc,))
            alt_rows = cur.fetchall()
            if alt_rows:
                print(f"   ⚠️  Contadores alternativos encontrados:")
                for idm, pare, baixa in alt_rows:
                    print(f"      - IdMaximo={idm}, Pare={pare}, Baixa={baixa}")
            exit(1)
        
        # Paso 4: Transformar IdMaximo a tag
        if len(id_maxim) >= 11:
            tag_name = f"{id_maxim[:5]}_{id_maxim[5:8]}_{id_maxim[8:11]}_CSM"
        else:
            tag_name = id_maxim + "_CSM"
        print(f"\n4️⃣ Tag generado: {tag_name}")
        
        # Paso 5: ite_consums_tags
        print(f"\n5️⃣ Buscar idTag en ite_consums_tags (tag = {tag_name})...")
        cur.execute('SELECT "idTag" FROM ga_landing.ite_consums_tags WHERE tag = %s', (tag_name,))
        row = cur.fetchone()
        if row:
            idtag = row[0]
            print(f"   ✅ idTag encontrado: {idtag}")
        else:
            print(f"   ❌ NO encontrado tag '{tag_name}' en ite_consums_tags")
            # Buscar tags similares
            cur.execute('SELECT tag, "idTag" FROM ga_landing.ite_consums_tags WHERE tag LIKE %s LIMIT 10', (f"{id_maxim[:5]}%",))
            similar = cur.fetchall()
            if similar:
                print(f"   ⚠️  Tags similares encontrados:")
                for t, it in similar:
                    print(f"      - {t} → idTag={it}")
            exit(1)
        
        print("\n" + "="*80)
        print(f"✅ FLUJO COMPLETO EXITOSO:")
        print(f"   CL00094 → Id={idgc} → IdMaximo={id_maxim} → Tag={tag_name} → idTag={idtag}")
        print("="*80 + "\n")
        
finally:
    conn.close()
