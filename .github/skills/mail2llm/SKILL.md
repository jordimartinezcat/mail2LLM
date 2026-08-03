---
name: mail2llm
description: Sistema de procesamiento automático de correos electrónicos para extracción de consumos de agua con Azure OpenAI e inserción en PostgreSQL y MSSQL. Incluye arquitectura completa, configuración de bases de datos, problemas conocidos y soluciones implementadas.
---

# mail2LLM - Sistema de Procesamiento de Consumos

## Descripción General

Sistema automatizado que procesa correos electrónicos con datos de consumos de agua, extrae información usando Azure OpenAI (gpt-4o-mini), y almacena los datos en PostgreSQL y MSSQL.

**Ubicación Producción**: `\\serversql4\C\nifi-2.0.0-M3\python\scripts\mail2LLM`  
**Frecuencia**: Cada 5 minutos via Apache NIFI scheduler  
**Repositorio**: https://github.com/jordimartinezcat/mail2LLM.git  

## Arquitectura del Sistema

### Flujo Completo
```
Email (Outlook OAuth2) 
  → LLM Extraction (Azure OpenAI gpt-4o-mini)
  → Pending Confirmations (pending_confirmations.json)
  → User Confirmation ("OK" reply)
  → Triple Insertion:
     1. PostgreSQL: ga_datalake.ite_consums_datarect (idtag, valor, data, tipus=3)
     2. PostgreSQL: ga_landing.consums_dia (Id, Data=END_OF_MONTH, Consum, especial=true)
     3. MSSQL: Consums.dbo.Consums_dia (Id, Data=END_OF_MONTH, Consum, especial=true)
```

### Estructura de Archivos Clave
```
main.py                    # Flujo principal: lectura email + confirmaciones
email_io/reader.py         # Extracción de tablas HTML con detección inteligente
email_io/oauth2.py         # OAuth2 para Outlook Office365
llm/processor.py           # Extracción LLM con Azure OpenAI
db/repository.py           # Lógica de inserción triple (PostgreSQL + MSSQL)
config/loader.py           # Carga de config.xml (DBConfig, MSSQLConfig)
pending_confirmations.json # Consumos pendientes de confirmación
config.xml                 # Configuración (NO en git, .gitignore)
```

## Configuración de Bases de Datos

### PostgreSQL (40.85.79.213:5432)
**Base de datos**: `goaigua_data`  
**Usuario**: `ga_nifisagecad`  
**Encoding**: `LATIN1`

#### Tablas Principales
- **ga_datalake.ite_consums_datarect**: Tabla principal de consumos
  - Campos: `data`, `idtag`, `valor`, `tipus`, `descrip`
  - Constraint: `UNIQUE(data, idtag, tipus)` - previene duplicados
  - `tipus=3` indica introducción desde correo

- **ga_landing.consums_dia**: Consumos diarios con flag especial
  - Campos: `Id` (contador), `Data` (último día del mes), `Consum`, `especial` (boolean)
  - Constraint: `UNIQUE(Id, Data)` - un consumo por contador/mes
  - `especial=true` marca consumos desde email

- **ga_landing.ite_consorciat**: Mapeo id_bcentral → Id (IdGC)
  - Campos: `id`, `id_bcentral` (ej: CL00068), `nom`

- **ga_landing.ite_comptadors**: Información de contadores
  - Campos: `Id` (ej: SEC, MESM), `IdGC`, `Descrip`, `IdMaximo`, `Pare`

- **ga_landing.ite_consums_tags**: Tags de consumo
  - Campos: `idTag` (integer), `tag` (string), `descTag`

- **ga_landing.ite_bcfact_clients**: Alias de empresas
  - Campos: `number` (id_bcentral), `alias` (nombre empresa)

### MSSQL (servercmp:1433)
**Base de datos**: `Consums`  
**Autenticación**: Windows (Trusted_Connection)

#### Tablas
- **dbo.Consums_dia**: Replica de consums_dia PostgreSQL
  - Campos: `Id`, `Data`, `Consum`, `especial`
  - Mismo constraint: `UNIQUE(Id, Data)`

### Dependencias Python
```txt
msal>=1.30.0              # OAuth2 Microsoft
psycopg2-binary>=2.9.9    # PostgreSQL
pyodbc>=5.0.0             # MSSQL (requiere ODBC Driver 17)
pypdf>=4.0.0              # Procesamiento PDFs
```

## Funciones Clave en db/repository.py

### `_get_contador_id_from_id_bcentral(id_bcentral: str, config: DBConfig) -> str | None`
Mapea id_bcentral (ej: CL00068) → Id del contador (ej: SEC)
- Busca en `ite_consorciat`: id_bcentral → Id (IdGC)
- Busca en `ite_comptadors`: IdGC → Id del contador
- Usado para insertar en `consums_dia`

### `_get_last_day_of_month(date: datetime) -> datetime`
Convierte cualquier fecha al último día del mes
- Ejemplo: 2026-07-15 → 2026-07-31
- Usado en `consums_dia` (ambas BD)

### `_insert_to_mssql_consums_dia(contador_id, fecha, valor, mssql_config) -> bool`
Inserta en MSSQL usando pyodbc con autenticación Windows

### `save_consumptions(consumptions, config, cache, mssql_config) -> tuple[int, list[str]]`
Inserción triple con dos flujos:
1. **PRIORIDAD 1**: Si viene `idtag` del HTML (atributo data-tag) → inserción directa
2. **PRIORIDAD 2** (fallback): Fuzzy matching por nombre empresa

## Problemas Conocidos y Soluciones

### 1. Outlook Strips Table IDs (RESUELTO)
**Problema**: Cuando usuarios responden a emails, Outlook elimina `id="taula_dades"`  
**Solución**: Detección por contenido en `email_io/reader.py:_extract_table_from_html()`
```python
has_id_col = bool(re.search(r'<th[^>]*>.*?\bId\b.*?</th>', table_html, re.IGNORECASE))
has_empresa = bool(re.search(r'<th[^>]*>.*?\bNom d\'empresa\b.*?</th>', table_html, re.IGNORECASE))
has_cl_pattern = bool(re.search(r'\bCL\d{5}\b', table_html))
```
**Commit**: 6fd6f49

### 2. Break Statement en Multipart Emails (RESUELTO)
**Problema**: Solo procesaba primera parte HTML, perdía contenido citado  
**Solución**: Concatenar todas las partes HTML en lugar de break
```python
if html_text:
    html_text += "\n" + decoded
else:
    html_text = decoded
```

### 3. EMATSA Duplicate Key (CONOCIDO)
**Problema**: idTag 20565 usado para Mas d'Enric (12,990 m³) y Urbanitzacions (16,833 m³)  
**Constraint**: `UNIQUE(data, idtag)` en `ite_consums_datarect` previene duplicados  
**Estado**: Error esperado, no es bug - constraint protege integridad

### 4. Fecha en consums_dia
**Regla**: SIEMPRE usar último día del mes, independiente de fecha original  
- Fecha original: 2026-07-15 → Inserción en consums_dia: **2026-07-31**
- Implementado con `_get_last_day_of_month()` usando `calendar.monthrange()`

## Mapeos de Contadores Conocidos

| id_bcentral | Empresa | Contador Id | idTag |
|-------------|---------|-------------|-------|
| CL00068 | Ajuntament de la Secuita | SEC | 20571 |
| CL00094 | MESSER el Morell | MESM | 20563 |
| CL00032 | EL CATLLAR - Mas Enric | CTLLME | 20564 |
| CL00032 | EL CATLLAR - Urbanitzacions | PVD07 | 20565 |
| CL00103 | (Desconocido) | CAR2 | - |

## Email Configuration

**Servidor**: outlook.office365.com:993 (IMAP/SSL)  
**Autenticación**: OAuth2  
**Client ID**: 02f1b85c-441f-4f77-9be3-65a826615d96  
**Token Cache**: token_cache.json  
**Permisos**: IMAP.AccessAsUser.All (Delegado)

### Carpetas IMAP
- `INBOX` - Entrada
- `0_Processats` - Procesados correctamente
- `0_Confirmacions_OK` - Confirmaciones afirmativas
- `0_Denegats` - Confirmaciones negativas
- `0_No_processats` - Errores de procesamiento

## LLM Configuration

**Proveedor**: Azure OpenAI  
**Modelo**: gpt-4o-mini  
**Endpoint**: https://mail2llm.cognitiveservices.azure.com/openai/deployments/gpt-4o-mini  
**API Version**: 2024-12-01-preview

## Deployment a Producción

```powershell
# En servidor de producción
cd \\serversql4\C\nifi-2.0.0-M3\python\scripts\mail2LLM
git pull

# Instalar dependencias nuevas (si hay)
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**IMPORTANTE**: `config.xml` NO está en git (.gitignore) - copiar manualmente si cambia estructura

## Comandos de Testing

### Test Inserción Local
```powershell
python test_insert_bd.py
```

### Test MSSQL
```powershell
python test_mssql_simple.py
```

### Test Inserción Directa consums_dia
```powershell
python test_insert_consums_dia_only.py
```

## Logging

**Ubicación**: `log/processMail.log.YYYY-MM-DD`  
**Rotación**: Diaria automática  
**Nivel**: INFO (DEBUG para consultas SQL)

## Últimos Cambios Importantes

### Commit 8a66f2c (2026-08-03) - Integración MSSQL
- Nueva clase `MSSQLConfig` en config/loader.py
- Función `_insert_to_mssql_consums_dia()` con autenticación Windows
- Inserción triple automática: datarect + consums_dia (PG) + Consums_dia (MSSQL)
- Agregado `pyodbc>=5.0.0` a requirements.txt

### Commit 28eefb6 - Inserción Dual PostgreSQL
- Nueva función `_get_contador_id_from_id_bcentral()`
- Inserción automática en `ga_landing.consums_dia` con `especial=true`
- Lógica de último día de mes implementada

### Commit 6fd6f49 - Detección Inteligente de Tablas
- Detección por contenido en lugar de atributo id
- Soluciona problema de Outlook stripping attributes

## Troubleshooting

### Error: "duplicate key value violates unique constraint"
**Causa**: Registro ya existe en tabla  
**Acción**: Normal para `ite_consums_datarect`, verificar si es reintento  
**Para consums_dia**: Verificar constraint `UNIQUE(Id, Data)`

### Error: "No se encontró IdGC en ite_consorciat"
**Causa**: id_bcentral no existe en base de datos  
**Acción**: Verificar que el id_bcentral es correcto y existe en `ite_bcfact_clients`

### Error: "Import 'pyodbc' could not be resolved"
**Causa**: pyodbc no instalado o no en PATH  
**Acción**: 
1. Instalar: `pip install pyodbc>=5.0.0`
2. Verificar ODBC Driver 17 for SQL Server instalado

### Error MSSQL Connection
**Causa**: Driver ODBC no instalado o autenticación Windows fallida  
**Acción**: Instalar ODBC Driver 17: `choco install sqlserver-odbcdriver`

## Notas de Desarrollo

- **NO modificar** `config.xml` en git - siempre en `.gitignore`
- **NO hacer** `Copy-Item` manual - usar `git pull` en producción
- **Fecha de consums_dia**: SIEMPRE último día del mes
- **especial=true**: Marca consumos desde correo (vs. otras fuentes)
- **tipus=3**: Tipo de consumo desde correo en `ite_consums_datarect`
- **Constraint duplicados**: Son protección, no bugs - verificar antes de intentar insertar

## Referencias Rápidas

### SQL Útiles
```sql
-- Ver consumos recientes con especial=true
SELECT * FROM ga_landing.consums_dia 
WHERE especial=true 
ORDER BY "Data" DESC LIMIT 10;

-- Ver mapeo contador
SELECT c."Id", c."IdGC", i.id_bcentral, i.nom
FROM ga_landing.ite_comptadors c
JOIN ga_landing.ite_consorciat i ON i.id = c."IdGC"
WHERE c."Id" = 'SEC';

-- Verificar MSSQL
SELECT * FROM Consums.dbo.Consums_dia 
WHERE especial=1 
ORDER BY Data DESC;
```

### Python Testing
```python
from config.loader import load_config
from db.repository import _get_contador_id_from_id_bcentral

config = load_config()
contador_id = _get_contador_id_from_id_bcentral('CL00068', config.db)
print(f"Contador: {contador_id}")  # Expected: SEC
```
