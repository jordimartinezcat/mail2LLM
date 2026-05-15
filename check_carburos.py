import psycopg2

conn = psycopg2.connect(
    host='40.85.79.213',
    port=5432,
    dbname='tcat_consumsaigua',
    user='iteuser',
    password='i735q5',
    options='-c client_encoding=UTF8'
)

cur = conn.cursor()
cur.execute("""
    SELECT number, alias 
    FROM ga_landing.ite_bcfact_clients 
    WHERE LOWER(alias) LIKE '%carburos%' OR LOWER(alias) LIKE '%cm%'
    ORDER BY alias
""")

rows = cur.fetchall()
print(f"Empresas encontradas: {len(rows)}")
print("-" * 60)
for row in rows:
    print(f"{row[0]:10} | {row[1]}")

conn.close()
