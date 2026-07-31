import email
import imaplib
import io
import logging
from email.header import decode_header
from email.message import Message
from typing import Generator

from pypdf import PdfReader

from config.loader import EmailConfig
from email_io.oauth2 import get_imap_oauth2_string

logger = logging.getLogger("processMail")


# ---------------------------------------------------------------------------
# Helpers de decodificación
# ---------------------------------------------------------------------------


def _decode_header_value(value: str | None) -> str:
    """Decodifica una cabecera MIME (Subject, From, etc.) a cadena de texto."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded_parts = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            decoded_parts.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(raw)
    return "".join(decoded_parts)


def _remove_non_insertable_rows(html: str) -> str:
    """
    Elimina del HTML las filas de tabla marcadas con data-insertar-bd="false".
    Estas filas son solo informativas y no deben procesarse para insertar en BD.
    
    Args:
        html: Contenido HTML del email
        
    Returns:
        HTML sin las filas marcadas como no insertables
    """
    import re
    
    # Patrón para detectar <tr data-insertar-bd="false">...</tr>
    # Usa DOTALL para capturar contenido multilínea
    pattern = r'<tr\s+data-insertar-bd\s*=\s*["\']false["\']\s*>.*?</tr>'
    
    cleaned_html = re.sub(pattern, '', html, flags=re.DOTALL | re.IGNORECASE)
    
    # Contar cuántas filas se eliminaron (solo para logging)
    removed_count = len(re.findall(pattern, html, flags=re.DOTALL | re.IGNORECASE))
    if removed_count > 0:
        logger.info("Eliminadas %d filas marcadas como no insertables (data-insertar-bd=false)", removed_count)
    
    return cleaned_html


def _extract_table_from_html(html: str) -> str:
    """
    Extrae la tabla HTML con id="taula_dades" del email INCLUYENDO el contexto previo.
    Busca desde el texto "Període:" o "Período:" hasta el final de la tabla para capturar
    la fecha del período (ej: "Juliol 2026") que el LLM necesita extraer.
    
    Esta tabla contiene los datos de consumo con estructura:
    - Primera celda contiene formato CLxxxxx-idtag para inserción directa en BD
    - Elimina respuestas citadas y contenido irrelevante
    
    Returns:
        HTML con contexto (período + tabla), o string vacío si no se encuentra
    """
    import re
    
    # 1. Buscar tabla con id="taula_dades"
    # Patrón: <table id="taula_dades"...>...</table>
    table_match = re.search(
        r'<table[^>]*id=["\']taula_dades["\'][^>]*>.*?</table>',
        html,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    if table_match:
        table_start = table_match.start()
        table_end = table_match.end()
        
        # Buscar texto de período ANTES de la tabla (últimos 2000 caracteres previos)
        context_start = max(0, table_start - 2000)
        context_html = html[context_start:table_end]
        
        logger.info("✅ Tabla 'taula_dades' + contexto extraídos del HTML (%d caracteres)", len(context_html))
        return context_html
    
    # 2. Si no se encuentra la tabla específica, buscar tabla con columnas de datos
    # La tabla de datos contiene: "Id", "Nom d'empresa", "Consum"
    logger.warning("⚠️  No se encontró tabla con id='taula_dades', buscando tabla con columnas de datos")
    
    # Buscar TODAS las tablas
    all_tables = re.findall(r'<table[^>]*>.*?</table>', html, flags=re.DOTALL | re.IGNORECASE)
    
    for table_html in all_tables:
        # Verificar si la tabla contiene las columnas esperadas
        has_id_col = re.search(r'<th[^>]*>\s*Id\s*</th>', table_html, re.IGNORECASE)
        has_empresa_col = re.search(r'<th[^>]*>\s*Nom\s+d[\'"]?empresa', table_html, re.IGNORECASE)
        has_consum_col = re.search(r'<th[^>]*>\s*Consum', table_html, re.IGNORECASE)
        
        # También buscar patrón CLxxxxx que indica datos reales
        has_cl_pattern = re.search(r'CL\d{5}', table_html, re.IGNORECASE)
        
        if (has_id_col or has_empresa_col or has_consum_col) or has_cl_pattern:
            # Esta es la tabla de datos
            table_match = re.search(re.escape(table_html), html)
            if table_match:
                table_start = table_match.start()
                table_end = table_match.end()
                context_start = max(0, table_start - 2000)
                context_html = html[context_start:table_end]
                logger.info("✅ Tabla con datos de consumo encontrada (%d caracteres)", len(context_html))
                return context_html
    
    # 3. Fallback: primera tabla general (puede ser firma u otra)
    logger.warning("⚠️  No se encontró tabla con datos, usando primera tabla genérica")
    table_match = re.search(r'<table[^>]*>.*?</table>', html, flags=re.DOTALL | re.IGNORECASE)
    
    if table_match:
        table_start = table_match.start()
        table_end = table_match.end()
        
        # Incluir contexto previo
        context_start = max(0, table_start - 2000)
        context_html = html[context_start:table_end]
        
        logger.info("✅ Primera tabla HTML + contexto extraídos (%d caracteres)", len(context_html))
        return context_html
    
    logger.warning("⚠️  No se encontró ninguna tabla HTML en el mensaje")
    return ""


def _extract_plain_body(msg: Message) -> str:
    """
    Extrae el cuerpo del mensaje:
    - Si es HTML: extrae la tabla con id="taula_dades" (formato HTML completo)
    - Si es texto plano: extrae y limpia el texto
    
    IMPORTANTE: Ahora devuelve HTML de tabla si está disponible (no texto plano),
    para que el LLM pueda extraer el formato CLxxxxx-idtag de la primera celda.
    """
    plain_text = None
    html_text = None
    
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition", "")):
                continue
                
            content_type = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            
            if not payload:
                continue
            
            decoded = payload.decode(charset, errors="replace")
            
            # Recopilar TODAS las partes (no hacer break)
            if content_type == "text/plain" and not plain_text:
                plain_text = decoded
            elif content_type == "text/html":
                # Concatenar TODO el HTML (incluye partes citadas)
                if html_text:
                    html_text += "\n" + decoded
                else:
                    html_text = decoded
    else:
        # Mensaje simple (no multipart)
        content_type = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        
        if payload:
            decoded = payload.decode(charset, errors="replace")
            if content_type == "text/plain":
                plain_text = decoded
            elif content_type == "text/html":
                html_text = decoded
    
    # PRIORIDAD 1: Si hay HTML, extraer tabla con id="taula_dades"
    if html_text:
        # Eliminar filas no insertables ANTES de extraer la tabla
        html_text = _remove_non_insertable_rows(html_text)
        
        # Intentar extraer tabla específica
        table_html = _extract_table_from_html(html_text)
        
        if table_html:
            # ✨ NUEVO: Devolver HTML de tabla directamente (no convertir a texto)
            # El LLM procesará el HTML y extraerá el formato CLxxxxx-idtag
            return table_html
        
        # Si no hay tabla, convertir HTML a texto plano (fallback)
        import re
        text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)  # Eliminar todos los tags
        text = re.sub(r'\s+', ' ', text)  # Colapsar espacios
        return _clean_body(_remove_email_thread(text.strip()))
    
    # PRIORIDAD 2: Si hay texto plano, usarlo
    if plain_text:
        return _clean_body(_remove_email_thread(plain_text))
    
    return ""


def _extract_pdf_attachments(msg: Message) -> list[str]:
    """
    Extrae el contenido de texto de todos los adjuntos PDF del mensaje.
    Retorna una lista de strings, uno por cada PDF encontrado.
    """
    pdf_contents = []
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Buscar adjuntos PDF
            if content_type == "application/pdf" or (
                "attachment" in content_disposition and 
                part.get_filename() and part.get_filename().lower().endswith(".pdf")
            ):
                filename = part.get_filename() or "unknown.pdf"
                try:
                    pdf_data = part.get_payload(decode=True)
                    if pdf_data:
                        # Extraer texto del PDF
                        pdf_file = io.BytesIO(pdf_data)
                        reader = PdfReader(pdf_file)
                        
                        text_parts = []
                        for page_num, page in enumerate(reader.pages, 1):
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(f"--- Página {page_num} ---\n{page_text}")
                        
                        if text_parts:
                            full_text = "\n\n".join(text_parts)
                            pdf_contents.append(f"[Adjunto PDF: {filename}]\n{full_text}")
                            logger.info("PDF extraído: %s (%d páginas)", filename, len(reader.pages))
                        else:
                            logger.warning("PDF sin texto extraíble: %s", filename)
                except Exception as exc:
                    logger.error("Error extrayendo PDF %s: %s", filename, exc)
    
    return pdf_contents


def _clean_body(text: str) -> str:
    """
    Normaliza el cuerpo del correo para facilitar la extracción por el LLM:
    - Elimina firmas/footers HTML típicos al inicio (Consorci, empresas)
    - Elimina líneas de firma y separadores típicos de email
    - Colapsa líneas en blanco múltiples en una sola
    - Normaliza tabulaciones y espacios múltiples en columnas alineadas
    - Elimina caracteres de control y líneas irrelevantes
    """
    import re as _re

    # Eliminar footer/firma del Consorci solo si aparece AL INICIO del mensaje (threads)
    # Eliminar todo desde el inicio hasta justo antes del primer "De:" de un thread
    if '&nbsp;' in text[:200] and 'destrueixin' in text[:2000]:
        # Buscar el primer "De:" después del footer que marca el inicio del contenido real
        match = _re.search(r'De:\s+\w', text, _re.IGNORECASE)
        if match:
            # Eliminar todo desde el inicio hasta (pero sin incluir) este "De:"
            logger.debug("Footer HTML del Consorci eliminado (hasta posición %d)", match.start())
            text = text[match.start():]
            text = text.lstrip()
    
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        # Eliminar líneas de firma típicas
        stripped = line.strip()
        if stripped in ("--", "—", "___", "---") or _re.match(r"^[-_=]{3,}$", stripped):
            break  # Todo lo que viene después es firma, descartar
        # Normalizar tabulaciones a espacios
        line = line.replace("\t", "    ")
        # Colapsar secuencias de más de 2 espacios internos a 2 (preserva alineación de tablas)
        # pero solo en líneas que no parecen tablas (sin múltiples columnas)
        if not _re.search(r"\s{3,}\S", line):
            line = _re.sub(r"  +", " ", line)
        cleaned.append(line.rstrip())

    # Colapsar líneas en blanco múltiples en una sola
    result = _re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned))
    return result.strip()


def _remove_email_thread(text: str) -> str:
    """
    Elimina correos antiguos de threads/forwards.
    Mantiene solo los correos de los últimos 2 meses desde hoy.
    IMPORTANTE: Preserva el texto ANTES del primer header de thread.
    Si no se pueden detectar fechas, limita a 10KB.
    """
    import re as _re
    from datetime import datetime, timedelta
    
    # Fecha límite: hace 2 meses
    cutoff_date = datetime.now() - timedelta(days=60)
    
    # Patrones de fecha en headers de emails en threads
    date_patterns = [
        (r'Enviado el:\s+\w+,\s+(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})', 'es_long'),
        (r'Sent:\s+\w+,\s+(\w+)\s+(\d+),\s+(\d{4})', 'en_long'),
        (r'Enviado el:\s+(\d{1,2})/(\d{1,2})/(\d{4})', 'es_short'),
        (r'Sent:\s+(\d{1,2})/(\d{1,2})/(\d{4})', 'en_short'),
        (r'Enviado:\s+\w+,\s+(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})', 'es_long'),  # "Enviado:" sin "el:"
    ]
    
    meses_es = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
        'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
    }
    meses_en = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
    }
    
    # Buscar todos los headers de thread (De: ... Enviado:)
    thread_headers = list(_re.finditer(
        r'\n\s*De:\s+[^\n]+\n\s*Enviado[^\n]*:\s+[^\n]+',
        text,
        _re.IGNORECASE | _re.MULTILINE
    ))
    
    if not thread_headers:
        # No hay threads detectables, limitar a 10KB
        if len(text) > 10000:
            return text[:10000] + "\n[... contenido truncado ...]"
        return text
    
    # Preservar el texto ANTES del primer header (es el mensaje más reciente)
    first_header_pos = thread_headers[0].start()
    text_before_first_header = text[:first_header_pos]
    
    # Intentar encontrar el primer correo antiguo (> 2 meses) DESPUÉS del primer header
    cut_position = None
    
    for match in thread_headers:
        header_text = match.group(0)
        email_date = None
        
        # Intentar parsear la fecha
        for pattern, date_type in date_patterns:
            date_match = _re.search(pattern, header_text, _re.IGNORECASE)
            if date_match:
                try:
                    if date_type == 'es_long':
                        day = int(date_match.group(1))
                        month_name = date_match.group(2).lower()
                        year = int(date_match.group(3))
                        month = meses_es.get(month_name)
                        if month:
                            email_date = datetime(year, month, day)
                    elif date_type == 'en_long':
                        month_name = date_match.group(1).lower()
                        day = int(date_match.group(2))
                        year = int(date_match.group(3))
                        month = meses_en.get(month_name)
                        if month:
                            email_date = datetime(year, month, day)
                    elif date_type in ('es_short', 'en_short'):
                        day = int(date_match.group(1))
                        month = int(date_match.group(2))
                        year = int(date_match.group(3))
                        email_date = datetime(year, month, day)
                    
                    if email_date:
                        break
                except (ValueError, AttributeError):
                    continue
        
        # Si encontramos una fecha antigua, cortar ahí
        if email_date and email_date < cutoff_date:
            cut_position = match.start()
            break
    
    # Construir el texto final: texto antes del primer header + contenido hasta el corte
    if cut_position is not None:
        # Mantener desde el inicio hasta la posición de corte
        text = text[:cut_position].rstrip()
    
    # Limitar longitud máxima de seguridad
    max_length = 10000
    if len(text) > max_length:
        text = text[:max_length] + "\n[... contenido truncado ...]"
    
    return text


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------


class EmailReader:
    """
    Gestiona la conexión IMAP y la descarga de mensajes nuevos (UNSEEN).

    Uso recomendado como context manager:

        with EmailReader(config.email) as reader:
            for uid, msg_data in reader.fetch_new_messages():
                ...
    """

    def __init__(self, config: EmailConfig) -> None:
        self.config = config
        self._conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def connect(self) -> None:
        logger.info(
            "Conectando al servidor IMAP %s:%d (SSL=%s)",
            self.config.server,
            self.config.port,
            self.config.ssl,
        )
        try:
            if self.config.ssl:
                self._conn = imaplib.IMAP4_SSL(self.config.server, self.config.port)
            else:
                self._conn = imaplib.IMAP4(self.config.server, self.config.port)

            if self.config.oauth2_client_id:
                # Autenticación OAuth2 (requerida para Outlook/Hotmail/Office 365)
                oauth2_string = get_imap_oauth2_string(
                    username=self.config.username,
                    client_id=self.config.oauth2_client_id,
                    token_cache_path=self.config.oauth2_token_cache,
                )
                self._conn.authenticate("XOAUTH2", lambda x: oauth2_string)
                logger.info("Sesión IMAP iniciada como '%s' (OAuth2)", self.config.username)
            else:
                # Autenticación básica (servidores que aún la soportan)
                self._conn.login(self.config.username, self.config.password)
                logger.info("Sesión IMAP iniciada como '%s' (basic auth)", self.config.username)

        except imaplib.IMAP4.error as exc:
            logger.error("Error al conectar con el servidor IMAP: %s", exc)
            raise

    def disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
                logger.info("Conexión IMAP cerrada correctamente")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error al cerrar la conexión IMAP: %s", exc)
            finally:
                self._conn = None

    # ------------------------------------------------------------------
    # Conteo de mensajes nuevos
    # ------------------------------------------------------------------

    def count_new_messages(self) -> int:
        """Devuelve el número total de mensajes de la carpeta (leídos y no leídos)."""
        if self._conn is None:
            raise RuntimeError("No hay conexión IMAP activa. Llama a connect() primero.")

        status, _ = self._conn.select(self.config.folder, readonly=True)
        if status != "OK":
            logger.error("No se pudo seleccionar la carpeta '%s'", self.config.folder)
            raise RuntimeError(f"No se puede abrir la carpeta: {self.config.folder}")

        status, data = self._conn.uid("search", None, "ALL")
        if status != "OK":
            logger.error("Fallo al buscar mensajes")
            return 0

        msg_ids = data[0].split() if data[0] else []
        count = len(msg_ids)
        logger.info("Mensajes en '%s': %d", self.config.folder, count)
        return count

    # ------------------------------------------------------------------
    # Descarga de mensajes
    # ------------------------------------------------------------------

    def fetch_new_messages(self) -> Generator[tuple[str, dict], None, None]:
        """
        Genera tuplas (uid, message_data) para cada mensaje UNSEEN de la carpeta
        configurada. Los mensajes se marcan como leídos (\\Seen) al ser descargados.

        Yields:
            uid:          Identificador numérico del mensaje en el servidor.
            message_data: Diccionario con claves subject, sender, date, body.
        """
        if self._conn is None:
            raise RuntimeError("No hay conexión IMAP activa. Llama a connect() primero.")

        # Seleccionar carpeta
        status, _ = self._conn.select(self.config.folder)
        if status != "OK":
            logger.error("No se pudo seleccionar la carpeta '%s'", self.config.folder)
            raise RuntimeError(f"No se puede abrir la carpeta: {self.config.folder}")

        logger.info("Buscando mensajes en '%s'", self.config.folder)
        status, data = self._conn.uid("search", None, "ALL")
        if status != "OK":
            logger.error("Fallo al buscar mensajes")
            return

        msg_ids: list[bytes] = data[0].split() if data[0] else []
        logger.info("Mensajes encontrados: %d", len(msg_ids))

        for msg_id in msg_ids:
            uid = msg_id.decode()
            try:
                status, raw_data = self._conn.uid("fetch", msg_id, "(RFC822)")
                if status != "OK" or not raw_data or raw_data[0] is None:
                    logger.warning("No se pudo descargar el mensaje ID %s", uid)
                    continue

                raw_bytes: bytes = raw_data[0][1]  # type: ignore[index]
                msg = email.message_from_bytes(raw_bytes)

                subject = _decode_header_value(msg.get("Subject"))
                sender = _decode_header_value(msg.get("From"))
                date = msg.get("Date", "")
                body = _extract_plain_body(msg)
                # Extraer PDFs adjuntos
                pdf_contents = _extract_pdf_attachments(msg)
                # Guardar mensaje raw completo para búsquedas avanzadas
                raw_text = raw_bytes.decode("utf-8", errors="ignore")

                message_data = {
                    "id": uid,
                    "subject": subject,
                    "sender": sender,
                    "date": date,
                    "body": body,
                    "pdf_contents": pdf_contents,  # Lista de contenidos de PDFs extraídos
                    "raw": raw_text,  # Mensaje completo para extraer UIDs de confirmación
                }

                logger.info(
                    "Mensaje descargado [%s] Asunto: '%s' | De: %s",
                    uid,
                    subject,
                    sender,
                )
                yield uid, message_data

            except Exception as exc:  # noqa: BLE001
                logger.error("Error procesando el mensaje ID %s: %s", uid, exc)

    # ------------------------------------------------------------------
    # Mover mensaje a otra carpeta
    # ------------------------------------------------------------------

    def move_message(self, msg_id: str, destination_folder: str) -> bool:
        """
        Mueve un mensaje a la carpeta destino usando COPY + DELETE + EXPUNGE.
        Crea la carpeta destino si no existe.
        Devuelve True si el movimiento fue exitoso.
        """
        if self._conn is None:
            raise RuntimeError("No hay conexión IMAP activa.")

        # Crear carpeta destino si no existe
        status, _ = self._conn.select(destination_folder)
        if status != "OK":
            logger.info("Creando carpeta '%s'", destination_folder)
            create_status, _ = self._conn.create(destination_folder)
            if create_status != "OK":
                logger.error("No se pudo crear la carpeta '%s'", destination_folder)
                return False

        # Volver a seleccionar la carpeta origen
        self._conn.select(self.config.folder)

        # Copiar a destino usando UID
        status, _ = self._conn.uid("copy", msg_id, destination_folder)
        if status != "OK":
            logger.error(
                "No se pudo copiar el mensaje [%s] a '%s'", msg_id, destination_folder
            )
            return False

        # Marcar como borrado en origen y expurgar usando UID
        self._conn.uid("store", msg_id, "+FLAGS", "\\Deleted")
        self._conn.expunge()

        logger.info(
            "Mensaje [%s] movido a '%s'", msg_id, destination_folder
        )
        return True

    # ------------------------------------------------------------------
    # Marcar mensaje como no leído
    # ------------------------------------------------------------------

    def mark_as_unread(self, msg_id: str) -> None:
        """Elimina el flag \\Seen del mensaje, devolviéndolo a no leído."""
        if self._conn is None:
            raise RuntimeError("No hay conexión IMAP activa.")
        self._conn.uid("store", msg_id, "-FLAGS", "\\Seen")
        logger.info("Mensaje [%s] marcado como no leído", msg_id)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "EmailReader":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False
