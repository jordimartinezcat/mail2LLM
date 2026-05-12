# mail2LLM

Procesa correos electrónicos con consumos de agua y los inserta en base de datos PostgreSQL mediante confirmación en dos pasos.

## 🔄 Flujo de Confirmación

El sistema implementa un flujo de **confirmación en dos pasos** para garantizar seguridad antes de insertar datos en la BD:

### 1️⃣ **Extracción de Consumos**
- El sistema lee correos nuevos del buzón
- Usa Azure OpenAI (gpt-4o-mini) para extraer datos de consumo:
  - Fecha
  - Empresa
  - Valor (m³)
- Guarda los consumos como **pendientes de confirmación**
- Envía un correo al administrador solicitando confirmación

### 2️⃣ **Confirmación por Email**
- El administrador recibe un correo con:
  - Resumen de consumos detectados
  - UID del mensaje original
  - Instrucciones de confirmación
- Para **confirmar** la inserción en BD, responde con:
  - `OK`
  - `CONFIRMAR`
  - `SÍ` / `SI`
  - `ACEPTAR`
- El sistema detecta la respuesta y:
  - Inserta los consumos en PostgreSQL
  - Elimina los consumos pendientes
  - Mueve el mensaje a la carpeta de procesados

### 3️⃣ **Rechazo**
- Si no responde o elimina el correo de confirmación:
  - Los consumos quedan pendientes (no se insertan)
  - Se pueden revisar en `pending_confirmations.json`

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

## 📊 Estado del Proyecto

**Versión actual**: 1.0 - Flujo de confirmación implementado
- ✅ Extracción con Azure OpenAI gpt-4o-mini
- ✅ Confirmación en dos pasos por email
- ✅ OAuth2 para Outlook IMAP/SMTP
- ✅ Inserción en PostgreSQL con validación
- ✅ Soporte SSL corporativo
- ✅ Notificaciones de errores

## 📄 Licencia

Proyecto interno - CCAAIT
