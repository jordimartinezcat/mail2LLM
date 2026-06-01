"""
Script para revisar el último correo en INBOX y ver su contenido.
"""

import imaplib
import email
import logging
from email.header import decode_header
from config.loader import load_config
from email_io.oauth2 import get_imap_oauth2_string

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)


def check_latest_email():
    """Lee el último correo de INBOX y muestra su contenido."""
    
    config = load_config("config.xml")
    
    # Conectar a IMAP con OAuth2
    auth_string = get_imap_oauth2_string(
        username=config.email.username,
        client_id=config.email.oauth2_client_id,
        token_cache_path=config.email.oauth2_token_cache
    )
    imap = imaplib.IMAP4_SSL(config.email.server, config.email.port)
    imap.authenticate("XOAUTH2", lambda x: auth_string)
    
    try:
        # Seleccionar INBOX
        imap.select("INBOX")
        
        # Buscar TODOS los mensajes
        status, messages = imap.search(None, "ALL")
        
        if status != "OK":
            logger.error("No se pudo buscar mensajes")
            return
        
        msg_ids = messages[0].split()
        
        if not msg_ids:
            logger.info("No hay mensajes en INBOX")
            return
        
        # Obtener el ÚLTIMO mensaje (más reciente)
        last_msg_id = msg_ids[-1]
        
        logger.info(f"Total mensajes en INBOX: {len(msg_ids)}")
        logger.info(f"Leyendo último mensaje ID: {last_msg_id.decode()}")
        
        # Fetch del mensaje completo
        status, msg_data = imap.fetch(last_msg_id, "(RFC822)")
        
        if status != "OK":
            logger.error("No se pudo obtener el mensaje")
            return
        
        raw_email = msg_data[0][1]
        email_message = email.message_from_bytes(raw_email)
        
        # Decodificar subject
        subject = ""
        if email_message["Subject"]:
            decoded = decode_header(email_message["Subject"])
            subject = ""
            for content, encoding in decoded:
                if isinstance(content, bytes):
                    subject += content.decode(encoding or "utf-8", errors="ignore")
                else:
                    subject += content
        
        # From
        from_addr = email_message.get("From", "")
        
        # Date
        date = email_message.get("Date", "")
        
        print("\n" + "="*80)
        print("ÚLTIMO EMAIL EN INBOX")
        print("="*80)
        print(f"From: {from_addr}")
        print(f"Subject: {subject}")
        print(f"Date: {date}")
        print("="*80)
        
        # Extraer body
        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body += payload.decode(charset, errors="ignore")
                    except:
                        pass
                
                elif content_type == "text/html" and "attachment" not in content_disposition and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        html_content = payload.decode(charset, errors="ignore")
                        # Extraer texto de HTML
                        from html.parser import HTMLParser
                        
                        class HTMLTextExtractor(HTMLParser):
                            def __init__(self):
                                super().__init__()
                                self.text = []
                            
                            def handle_data(self, data):
                                self.text.append(data)
                            
                            def get_text(self):
                                return ' '.join(self.text)
                        
                        parser = HTMLTextExtractor()
                        parser.feed(html_content)
                        body = parser.get_text()
                    except:
                        pass
        else:
            try:
                payload = email_message.get_payload(decode=True)
                charset = email_message.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="ignore")
            except:
                body = str(email_message.get_payload())
        
        print("\nBODY:")
        print("-"*80)
        print(body[:3000])  # Primeros 3000 caracteres
        if len(body) > 3000:
            print(f"\n... (truncado, total {len(body)} caracteres)")
        print("-"*80)
        
        # Verificar adjuntos
        has_attachments = False
        if email_message.is_multipart():
            for part in email_message.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    has_attachments = True
                    print(f"\nAdjunto detectado: {filename}")
        
        if not has_attachments:
            print("\nNo hay adjuntos")
        
        print("\n" + "="*80)
    
    finally:
        try:
            imap.close()
            imap.logout()
        except:
            pass


if __name__ == "__main__":
    check_latest_email()
