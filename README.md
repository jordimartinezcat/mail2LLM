# mail2LLM

Procesa correos electrónicos con consumos de agua y los inserta en base de datos PostgreSQL mediante confirmación en dos pasos.

**Idioma**: Sistema en catalán (emails de confirmación y mensajes del sistema)

## � Quick Start / Contexto Rápido

**Para nueva sesión de desarrollo:**

1. **Estado actual**: Sistema funcional con confirmación en 2 pasos, emails HTML en catalán
2. **Problema activo**: Confirmación selectiva (1,3,5) tiene bugs en regex - captura números del texto citado
3. **Workaround**: Usar confirmación total (OK) hasta resolver bug
4. **Ejecución**: Se ejecuta desde Apache NIFI cada 5 minutos (recomendado, no 1 min)
5. **Base de datos**: Deshabilitada por defecto en config (`enabled=false`)
6. **Archivos críticos**:
   - `main.py` línea ~167: Regex bugueado para números selectivos
   - `pending_confirmations.json`: Estado actual de pendientes
   - `config.xml`: No en git, configuración local completa
   - `email_io/notifier.py`: Emails HTML en catalán

**Último commit**: `cf7507b` (12 May 2026) - Sistema confirmación 2 pasos

**Comandos útiles**:
```bash
python test_send_email.py          # Test con HTML
python main.py                      # Procesar emails
python refresh_token.py             # Renovar OAuth2
```

**Archivos pendientes**: Ver `pending_confirmations.json` para consumos sin confirmar

---

## �🔄 Flujo de Confirmación en 2 Pasos

El sistema implementa un flujo de **confirmación en dos pasos** para garantizar seguridad antes de insertar datos en la BD:

### 1️⃣ **Extracción de Consumos**
- El sistema lee correos nuevos del buzón INBOX
- Usa Azure OpenAI (gpt-4o-mini) para extraer datos de consumo:
  - Fecha
  - Empresa (nombre completo)
  - Valor (m³)
  - Unidades
- **Soporte completo para emails HTML**: El LLM procesa correctamente tablas HTML, estilos CSS, y texto enriquecido
- **✨ NUEVO: Soporte para archivos PDF adjuntos**: 
  - Detecta y extrae automáticamente el contenido de todos los PDFs adjuntos
  - Combina el cuerpo del email con el contenido de los PDFs
  - El LLM procesa ambas fuentes de información simultáneamente
  - Soporta múltiples PDFs por email
  - Extrae texto de todas las páginas del PDF
- Guarda los consumos como **pendientes de confirmación** en `pending_confirmations.json`
- Envía un correo HTML al administrador solicitando confirmación
- Mueve el mensaje original a `0_Processats`

### 2️⃣ **Confirmación por Email (Catalán)**
- El administrador recibe un **correo HTML profesional** con:
  - Tabla visual con todos los consumos detectados
  - UID del mensaje original en el subject: `[CONFIRMACIÓ #142]`
  - Información del remitente y asunto original
  - Instrucciones claras en catalán
  
#### **Opciones de confirmación:**

**A) Confirmación TOTAL (todos los consumos):**
Responder con cualquiera de estas palabras:
- `OK`
- `CONFIRMAR`
- `SÍ` / `SI`
- `ACEPTAR`
- `TOTS` / `TODOS`
- `CONFIRMO` / `ACEPTO`

**B) Confirmación SELECTIVA (líneas específicas):** ⚠️ **EN DESARROLLO - BUGS CONOCIDOS**
Responder con:
- `CONFIRMAR 1,3,5` → Confirma solo las líneas 1, 3 y 5
- `1,2` → Confirma solo líneas 1 y 2
- `1 3 5` → Acepta separación por espacios o comas

⚠️ **PROBLEMA CONOCIDO**: El regex de extracción de números tiene fallos:
- A veces captura números del texto citado del email original
- El patrón `r'^\s*([\d,\s]+?)\s*$'` no funciona consistentemente
- Se recomienda usar **confirmación total (OK)** hasta resolver el bug
- Los consumos pendientes quedan en `pending_confirmations.json` y se pueden confirmar en futuras ejecuciones

**C) Rechazo (futuro):**
- Si no responde: Los consumos quedan pendientes (no se insertan)
- Carpeta `0_Denegats` preparada pero sin lógica implementada

### 3️⃣ **Procesamiento de Confirmación**
- El sistema detecta la respuesta por UID en subject: `[CONFIRMACIÓ #142]`
- Extrae el UID con prioridad:
  1. Subject: `[CONFIRMACIÓ #142]`
  2. Body: `(ID de confirmació: 142)`
  3. Raw message (búsqueda en texto completo)
- Si confirmación total: Inserta TODOS los consumos en PostgreSQL
- Si confirmación selectiva: Inserta solo las líneas especificadas (si funciona el regex)
- Elimina consumos confirmados de `pending_confirmations.json`
- Mueve el mensaje de confirmación a `0_Confirmacions_OK`

## � Organización de Carpetas de Correo

El sistema organiza automáticamente los mensajes procesados en carpetas IMAP:

| Carpeta | Contenido | Descripción |
|---------|-----------|-------------|
| **INBOX** | Mensajes nuevos | Bandeja de entrada principal |
| **0_Processats** | Mensajes originales procesados | Emails con consumos extraídos correctamente, pendientes de confirmación |
| **0_Confirmacions_OK** | Confirmaciones afirmativas | Respuestas "OK" que insertaron datos en BD |
| **0_Denegats** | Confirmaciones negativas | Respuestas de rechazo (futuro) |
| **0_No_processats** | Mensajes con errores | Emails sin consumos, error LLM, datos incompletos, etc. |

**Ventajas de esta estructura:**
- ✅ Evita reprocesamiento infinito de errores
- ✅ Auditoría clara de cada flujo
- ✅ Separación entre originales y confirmaciones
- ✅ Fácil identificación de problemas

## �📁 Estructura del Proyecto

```
mail2LLM/
├── config.xml                    # Configuración (no en git)
├── config.xml.example            # Plantilla de configuración
├── pending_confirmations.json    # Consumos pendientes de confirmación
├── token_cache.json              # Cache OAuth2 (no en git)
├── main.py                       # Punto de entrada principal
├── pending_confirmations.py      # Gestión de pendientes
├── config/
│   ├── loader.py                 # Carga configuración XML
├── db/
│   ├── repository.py             # Operaciones PostgreSQL
├── email_io/
│   ├── reader.py                 # Lectura IMAP con OAuth2
│   ├── notifier.py               # Envío de confirmaciones y notificaciones
│   ├── oauth2.py                 # Autenticación OAuth2 para Outlook
├── llm/
│   └── processor.py              # Extracción con Azure OpenAI
└── logger_setup.py               # Configuración de logging
```

## ⚙️ Configuración

### 1. Copiar plantilla de configuración
```bash
copy config.xml.example config.xml
```

### 2. Editar `config.xml`

#### Email (IMAP con OAuth2)
```xml
<email>
  <server>outlook.office365.com</server>
  <port>993</port>
  <username>tu_correo@dominio.com</username>
  <ssl>true</ssl>
  <folder>INBOX</folder>
  <!-- Carpetas de destino según resultado del procesamiento -->
  <folder_processed>0_Processats</folder_processed>
  <folder_confirmed>0_Confirmacions_OK</folder_confirmed>
  <folder_rejected>0_Denegats</folder_rejected>
  <folder_errors>0_No_processats</folder_errors>
  <oauth2_client_id>TU_CLIENT_ID</oauth2_client_id>
  <oauth2_token_cache>token_cache.json</oauth2_token_cache>
</email>
```

#### LLM (Azure OpenAI)
```xml
<llm>
  <provider>azure_openai</provider>
  <api_key>TU_API_KEY</api_key>
  <model>gpt-4o-mini</model>
  <endpoint>https://RECURSO.openai.azure.com/openai/deployments/gpt-4o-mini</endpoint>
  <api_version>2024-12-01-preview</api_version>
  <verify_ssl>true</verify_ssl>
  <ca_bundle></ca_bundle>
</llm>
```

**⚠️ IMPORTANTE - Azure OpenAI Restrictions:**
- ❌ **NO enviar**: `temperature`, `top_p`, `max_tokens`, `response_format`
- ✅ El código ya maneja esto automáticamente en `llm/processor.py`
- 🔥 Azure gpt-4o-mini rechaza estos parámetros con error 400
- 📝 Usa solo: `messages` y acepta valores por defecto

**Ejemplo de error si envías parámetros extra:**
```
BadRequestError: Error code: 400
Unsupported value: 'temperature' does not support 0.1
```

**Configuración actual en código (NO modificar):**
```python
# llm/processor.py
response = client.chat.completions.create(
    model=config.model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    # SIN temperature, max_tokens, etc.
)
```

#### Notificaciones (SMTP con OAuth2)
```xml
<notifications>
  <enabled>true</enabled>
  <smtp_server>smtp-mail.outlook.com</smtp_server>
  <smtp_port>587</smtp_port>
  <smtp_tls>true</smtp_tls>
  <smtp_user>tu_correo@dominio.com</smtp_user>
  <from>tu_correo@dominio.com</from>
  <to>admin@dominio.com</to>
</notifications>
```

#### Base de Datos (PostgreSQL)
```xml
<db>
  <enabled>true</enabled>
  <host>servidor.dominio.com</host>
  <port>5432</port>
  <database>nombre_bd</database>
  <username>usuario</username>
  <password>contraseña</password>
  <consorciat_name_field>nom</consorciat_name_field>
  <match_threshold>0.6</match_threshold>
  <client_encoding>LATIN1</client_encoding>
</db>
```

## 🚀 Instalación

### 1. Crear entorno virtual
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar OAuth2 para Outlook

#### Registrar aplicación en Azure Portal
1. Portal: https://portal.azure.com → Azure Active Directory → App registrations
2. Crear nueva aplicación
3. **Permisos API**:
   - `IMAP.AccessAsUser.All` (Delegado)
   - `SMTP.Send` (Delegado)
4. **URI de redirección**: `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. **Tipo de cuenta**: Cuentas en cualquier directorio organizacional y cuentas personales de Microsoft

#### Obtener token inicial
```bash
python refresh_token.py
```
Sigue las instrucciones en el navegador para autorizar la aplicación.

## 📧 Uso

### Ejecución manual
```bash
python main.py
```

### Ejecución programada (Windows Task Scheduler)
```xml
<Task>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T09:00:00</StartBoundary>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>C:\Python312\python.exe</Command>
      <Arguments>D:\mail2LLM\main.py</Arguments>
      <WorkingDirectory>D:\mail2LLM</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

## 📝 Logs

Los logs se guardan en `log/processMail.log` con rotación automática:
- Máximo 5 MB por archivo
- 3 backups históricos
- Formato: `YYYY-MM-DD HH:MM:SS | NIVEL | mensaje`

## 🔒 Seguridad

- ✅ OAuth2 para Outlook (sin contraseñas en texto plano)
- ✅ Confirmación en dos pasos antes de insertar en BD
- ✅ Configuración excluida de Git (`.gitignore`)
- ✅ Soporte para certificados SSL corporativos (Fortinet, etc.)
- ✅ Validación de empresas contra base de datos
- ✅ Notificaciones de errores por correo

## 🛠️ Solución de Problemas

### Error SSL con firewall corporativo
Si ves errores `[SSL: CERTIFICATE_VERIFY_FAILED]`:

1. Exportar certificado corporativo (Fortinet/Zscaler):
```powershell
# Ver certificados instalados
certmgr.msc

# Exportar como Base-64 encoded X.509 (.CER)
```

2. Configurar en `config.xml`:
```xml
<ca_bundle>C:\certs\fortinet.pem</ca_bundle>
```

O deshabilitar verificación (NO recomendado en producción):
```xml
<verify_ssl>false</verify_ssl>
```

### Error "Unsupported value: 'temperature'"
Azure OpenAI gpt-4o-mini solo acepta `temperature=1` (default). El código ya lo maneja automáticamente eliminando parámetros incompatibles.

### Consumos no detectados
- Verifica que el correo tenga estructura clara:
  - Tabla con empresa y valor
  - Lista alineada (empresa | valor)
  - Texto libre con indicaciones claras
- El LLM busca: fecha, empresa, valor en m³
- Los registros incompletos se marcan como error

### Email en catalán vs castellano
- **Emails de confirmación**: 100% en catalán
- **Logs del sistema**: Mezclados (catalán/castellano)
- **Emails de entrada**: Soporta ambos idiomas (LLM multilingüe)
- **Instrucciones de confirmación**: Catalán prioritario

**Ejemplo de email de confirmación enviado:**
```
Subject: [CONFIRMACIÓ #176] Consums: Consumo de agua - Abril 2026

S'han extret 3 consum(s) del següent correu:
  Remitent: consums@ccaait.cat
  Assumpte: Consumo de agua - Abril 2026
  UID: 176

┌────────┬────────────┬────────────────────┬──────────┐
│   #    │    Data    │      Empresa       │  Consum  │
├────────┼────────────┼────────────────────┼──────────┤
│   1    │ 2026-04-30 │ ACME Industrias SA │ 1250.5m³ │
│   2    │ 2026-04-30 │ Beta Solutions     │  342.0m³ │
│   3    │ 2026-04-30 │ Gamma Tech Ltd     │  875.25m³│
└────────┴────────────┴────────────────────┴──────────┘

⚠️ Acció Requerida

Per CONFIRMAR la inserció a la base de dades, respon aquest 
correu amb una de les següents paraules:

  OK | CONFIRMAR | SÍ | ACEPTAR

Nota: També pots confirmar consums específics responent amb 
CONFIRMAR 1,3,5 (números de línia)

Per REBUTJAR, simplement ignora aquest missatge.

(ID de confirmació: 176)
```

## 📊 Estats del Proyecto (Mayo 2026)

**Versión actual**: 2.0 - Sistema de confirmación en 2 pasos con emails HTML en catalán

### ✅ Funcionalidades Implementadas

| Funcionalidad | Estado | Notas |
|---------------|--------|-------|
| Extracción LLM (Azure OpenAI gpt-4o-mini) | ✅ Funcional | Sin parámetros extras (temperature, etc.) |
| Soporte emails HTML | ✅ Funcional | LLM procesa tablas HTML correctamente |
| **Soporte archivos PDF adjuntos** | ✅ **NUEVO** | Extrae texto de PDFs y combina con email |
| Confirmación 2 pasos | ✅ Funcional | Emails en catalán, diseño profesional |
| Confirmación TOTAL (OK) | ✅ Funcional | Detecta: OK, SÍ, CONFIRMAR, TOTS, ACEPTAR |
| Confirmación SELECTIVA (1,3,5) | ⚠️ **CON BUGS** | Regex captura números del texto citado |
| OAuth2 Outlook IMAP/SMTP | ✅ Funcional | Token cache automático |
| Organización carpetas IMAP | ✅ Funcional | 4 carpetas: Processats, Confirmacions_OK, Denegats, No_processats |
| UID en subject | ✅ Funcional | `[CONFIRMACIÓ #142]` - extracción robusta |
| Inserción PostgreSQL | ✅ Funcional | Fuzzy matching empresas, validación |
| Gestión pendientes JSON | ✅ Funcional | `pending_confirmations.json` |
| Notificaciones error | ✅ Funcional | Emails con adjuntos de errores |
| Soporte SSL corporativo | ✅ Funcional | Fortinet certificates |
| Logging rotativo | ✅ Funcional | 5MB max, 3 backups |

### ⚠️ Problemas Conocidos

#### 1. **Confirmación selectiva (CRÍTICO)**
**Síntoma**: Al responder `1,3` el sistema confirma todos los consumos o números incorrectos

**Causa**: Regex en `main.py` línea ~167:
```python
match = re.search(r'^\s*([\d,\s]+?)\s*$', first_lines, re.MULTILINE)
```
Este patrón captura números del **texto citado** (email original incluido en la respuesta), no solo del cuerpo nuevo.

**Solución temporal**: Usar confirmación TOTAL (responder `OK`)

**Solución definitiva**: 
- Usar solo las primeras 2-3 líneas antes de salto de línea vacía
- Detectar `________` o `>` como inicio de texto citado
- Parsear headers `From:` / `Date:` como delimitador

#### 2. **Carpeta 0_Denegats sin uso**
- Preparada pero sin lógica implementada
- No hay detección de keywords: RECHAZAR, NO, DENEGAR

#### 3. **Base de datos deshabilitada por defecto**
- En `config.xml`: `<enabled>false</enabled>`
- Para activar en producción cambiar a `true`

### 🚀 Integraciones

#### Apache NIFI
El usuario menciona ejecutar desde NIFI:
- **Frecuencia recomendada**: **5 minutos** (no 1 minuto)
- **Razón**: Evitar throttling de Office 365 (límites IMAP)
- **Comando**: `python d:\Projects\Python\mail2LLM\main.py`
- **Working directory**: `d:\Projects\Python\mail2LLM`

**Alternativas**:
- **Windows Task Scheduler**: Trigger cada 5 minutos
- **Cron (Linux)**: `*/5 * * * * cd /path && python main.py`
- **IMAP IDLE** (futuro): Notificaciones push en tiempo real

### 📂 Archivos de Estado

| Archivo | Contenido | Git | Descripción |
|---------|-----------|-----|-------------|
| `pending_confirmations.json` | Consumos pendientes | ❌ No | Estado actual de confirmaciones pendientes |
| `token_cache.json` | Token OAuth2 | ❌ No | Refresh token para autenticación |
| `config.xml` | Configuración completa | ❌ No | Credenciales, endpoints, carpetas |
| `log/processMail.log` | Logs aplicación | ❌ No | Historial de ejecuciones |

#### Estructura de `pending_confirmations.json`

```json
{
  "176": {
    "subject": "Consumo de agua - Abril 2026",
    "sender": "consums@ccaait.cat",
    "date": "Tue, 12 May 2026 14:48:32 +0000",
    "body": "Email original completo...",
    "timestamp": "2026-05-12T16:48:50.123456",
    "consumptions": [
      {
        "fecha": "2026-04-30",
        "empresa": "ACME Industrias SA",
        "valor": 1250.5,
        "unidades": "m3"
      },
      {
        "fecha": "2026-04-30",
        "empresa": "Beta Solutions",
        "valor": 342.0,
        "unidades": "m3"
      }
    ]
  },
  "177": {
    "subject": "Otro mensaje pendiente...",
    ...
  }
}
```

**Notas:**
- Clave del dict = UID del mensaje IMAP original
- `consumptions` = array de consumos extraídos por el LLM
- Al confirmar TOTAL → se elimina toda la entrada
- Al confirmar SELECTIVA (1,3) → se elimina solo esos consumos, resto queda
- Archivo se limpia automáticamente al confirmar

### 🔧 Utilidades de Test

```bash
# Enviar email de prueba HTML (3 consumos)
python test_send_email.py

# Enviar email de prueba texto plano
python test_send_email.py --text

# Obtener nuevo token OAuth2
python refresh_token.py

# Confirmación manual (desarrollo)
python send_confirmation.py
```

### 📝 Commits Importantes

- **cf7507b** (12 May 2026): Sistema de confirmación en 2 pasos con emails HTML
  - 10 archivos modificados
  - 1,031 líneas añadidas
  - Emails en catalán con MIMEMultipart
  - Organización automática de carpetas
  - Confirmación selectiva (con bugs)

- **1d1f1ec** (anterior): Versión working sin confirmación
  - Extracción directa a BD
  - Sin flujo de aprobación

### 🐛 Debug Info

**Para diagnosticar problemas de confirmación selectiva:**
1. Activar logging DEBUG en `logger_setup.py`:
   ```python
   logging.basicConfig(level=logging.DEBUG)
   ```

2. Buscar en logs:
   ```
   Analizando confirmación - Primeras líneas: ...
   Match encontrado con 'CONFIRMAR': ...
   Confirmació SELECTIVA: línies [1, 3, 5]
   ```

3. Verificar `pending_confirmations.json` antes y después

### 🎯 Próximos Pasos Sugeridos

1. ⚠️ **FIX CRÍTICO**: Arreglar regex confirmación selectiva
2. 🔨 Implementar rechazo (keywords: RECHAZAR, NO, DENEGAR)
3. 📧 Añadir botón "Marcar como spam" en emails de confirmación
4. 🔔 IMAP IDLE para notificaciones en tiempo real (eliminar polling)
5. 📊 Dashboard web para revisar pendientes (Flask/FastAPI)
6. 🧪 Tests unitarios (pytest) para funciones críticas
7. 🐳 Dockerización del proyecto

## 📄 Licencia

Proyecto interno - CCAAIT
