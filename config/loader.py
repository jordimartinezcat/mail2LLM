import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass
class EmailConfig:
    server: str
    port: int
    username: str
    password: str
    ssl: bool
    folder: str
    processed_folder: str = "0000_processed"
    # OAuth2 (requerido para Outlook/Hotmail; vacío si se usa autenticación básica)
    oauth2_client_id: str = ""
    oauth2_token_cache: str = "token_cache.json"


@dataclass
class LLMConfig:
    provider: str
    api_key: str
    model: str
    endpoint: str = "http://localhost:11434"
    api_version: str = "2024-12-01-preview"


@dataclass
class NotificationConfig:
    enabled: bool
    smtp_server: str
    smtp_port: int
    smtp_tls: bool
    smtp_user: str
    smtp_password: str
    from_addr: str
    to_addrs: list


@dataclass
class DBConfig:
    enabled: bool
    host: str
    port: int
    database: str
    username: str
    password: str
    consorciat_name_field: str = "nom"  # columna de ga_landing.ite_consorciat con el nombre de empresa
    match_threshold: float = 0.6        # llindar mínim de similitud (0.0–1.0) per acceptar una coincidència
    client_encoding: str = "LATIN1"     # encoding del servidor PostgreSQL (LATIN1, UTF8, WIN1252...)

@dataclass
class AppConfig:
    email: EmailConfig
    llm: LLMConfig
    notifications: NotificationConfig
    db: DBConfig


def load_config(config_path: str | None = None) -> AppConfig:
    """
    Carga la configuración desde config.xml.
    Por defecto busca config.xml en el directorio raíz del proyecto.
    """
    if config_path is None:
        # __file__ és config/loader.py → pujar un nivell per arribar a l'arrel del projecte
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.xml"
        )

    if not os.path.isfile(config_path):
        raise FileNotFoundError(
            f"Fichero de configuración no encontrado: {config_path}\n"
            "Copia config.xml.example a config.xml y rellena tus credenciales."
        )

    tree = ET.parse(config_path)
    root = tree.getroot()

    # --- Email -----------------------------------------------------------------
    email_elem = root.find("email")
    if email_elem is None:
        raise ValueError("El elemento <email> no existe en config.xml")

    email_config = EmailConfig(
        server=_require(email_elem, "server", "email/server"),
        port=int(email_elem.findtext("port") or "993"),
        username=_require(email_elem, "username", "email/username"),
        password=(email_elem.findtext("password") or "").strip(),
        ssl=(email_elem.findtext("ssl") or "true").strip().lower() == "true",
        folder=(email_elem.findtext("folder") or "INBOX").strip(),
        processed_folder=(email_elem.findtext("processed_folder") or "0000_processed").strip(),
        oauth2_client_id=(email_elem.findtext("oauth2_client_id") or "").strip(),
        oauth2_token_cache=(email_elem.findtext("oauth2_token_cache") or "token_cache.json").strip(),
    )

    # --- LLM -------------------------------------------------------------------
    llm_elem = root.find("llm")
    llm_config = LLMConfig(
        provider=(llm_elem.findtext("provider") or "ollama").strip() if llm_elem is not None else "ollama",
        api_key=(llm_elem.findtext("api_key") or "").strip() if llm_elem is not None else "",
        model=(llm_elem.findtext("model") or "qwen3.5:4b").strip() if llm_elem is not None else "qwen3.5:4b",
        endpoint=(llm_elem.findtext("endpoint") or "http://localhost:11434").strip() if llm_elem is not None else "http://localhost:11434",
        api_version=(llm_elem.findtext("api_version") or "2024-12-01-preview").strip() if llm_elem is not None else "2024-12-01-preview",
    )

    # --- Notifications --------------------------------------------------------
    notif_elem = root.find("notifications")
    if notif_elem is not None:
        to_text = (notif_elem.findtext("to") or "").strip()
        to_addrs = [a.strip() for a in to_text.split(",") if a.strip()]
        notifications = NotificationConfig(
            enabled=(notif_elem.findtext("enabled") or "false").strip().lower() == "true",
            smtp_server=(notif_elem.findtext("smtp_server") or "").strip(),
            smtp_port=int(notif_elem.findtext("smtp_port") or "587"),
            smtp_tls=(notif_elem.findtext("smtp_tls") or "true").strip().lower() == "true",
            smtp_user=(notif_elem.findtext("smtp_user") or "").strip(),
            smtp_password=(notif_elem.findtext("smtp_password") or "").strip(),
            from_addr=(notif_elem.findtext("from") or "").strip(),
            to_addrs=to_addrs,
        )
    else:
        notifications = NotificationConfig(
            enabled=False,
            smtp_server="",
            smtp_port=587,
            smtp_tls=True,
            smtp_user="",
            smtp_password="",
            from_addr="",
            to_addrs=[],
        )

    # --- DB -------------------------------------------------------------------
    db_elem = root.find("db")
    if db_elem is not None:
        db_config = DBConfig(
            enabled=(db_elem.findtext("enabled") or "false").strip().lower() == "true",
            host=(db_elem.findtext("host") or "localhost").strip(),
            port=int(db_elem.findtext("port") or "5432"),
            database=_require(db_elem, "database", "db/database") if (db_elem.findtext("enabled") or "").strip().lower() == "true" else (db_elem.findtext("database") or "").strip(),
            username=(db_elem.findtext("username") or db_elem.findtext("user") or "").strip(),
            password=(db_elem.findtext("password") or "").strip(),
            consorciat_name_field=(db_elem.findtext("consorciat_name_field") or "nom").strip(),
            match_threshold=float(db_elem.findtext("match_threshold") or "0.6"),
            client_encoding=(db_elem.findtext("client_encoding") or "LATIN1").strip(),
        )
    else:
        db_config = DBConfig(
            enabled=False,
            host="localhost",
            port=5432,
            database="",
            username="",
            password="",
        )

    return AppConfig(email=email_config, llm=llm_config, notifications=notifications, db=db_config)


def _require(element: ET.Element, tag: str, full_path: str) -> str:
    value = element.findtext(tag)
    if not value or not value.strip():
        raise ValueError(f"El campo obligatorio <{full_path}> está vacío en config.xml")
    return value.strip()
