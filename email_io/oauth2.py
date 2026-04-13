import logging
import os

import msal

logger = logging.getLogger("processMail")

# Endpoint válido para cuentas personales (hotmail, outlook.com, live.com)
# y cuentas corporativas/educativas (Azure AD)
_AUTHORITY = "https://login.microsoftonline.com/common"

# Scopes necesarios para IMAP + SMTP OAuth2
# offline_access lo gestiona MSAL internamente — no incluirlo explícitamente
_SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]


def get_imap_oauth2_string(
    username: str,
    client_id: str,
    token_cache_path: str = "token_cache.json",
) -> bytes:
    """
    Obtiene un access token OAuth2 para IMAP y devuelve la cadena XOAUTH2
    codificada en base64 lista para usar con imaplib.authenticate().

    - Primera ejecución: inicia un device code flow (requiere que el usuario
      abra un navegador e introduzca el código mostrado en consola).
    - Ejecuciones posteriores: renueva el token silenciosamente usando el
      refresh token almacenado en token_cache_path — completamente desatendido.
    """
    cache = msal.SerializableTokenCache()

    if os.path.exists(token_cache_path):
        with open(token_cache_path, "r", encoding="utf-8") as fh:
            cache.deserialize(fh.read())
        logger.info("Caché de token OAuth2 cargada desde '%s'", token_cache_path)

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=_AUTHORITY,
        token_cache=cache,
    )

    # Intentar renovar silenciosamente
    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])
        if result:
            logger.info("Token OAuth2 renovado silenciosamente (refresh token)")

    # Si no hay token válido → device code flow (interactivo, solo la primera vez)
    if not result:
        logger.info("No hay token cacheado. Iniciando device code flow...")
        flow = app.initiate_device_flow(scopes=_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(
                f"Error iniciando device code flow: {flow.get('error_description', flow)}"
            )

        # Mostrar instrucciones al usuario
        print("\n" + "=" * 60)
        print("  AUTORIZACIÓN OAUTH2 REQUERIDA (solo la primera vez)")
        print("=" * 60)
        print(f"  1. Abre en el navegador: {flow['verification_uri']}")
        print(f"  2. Introduce el código:  {flow['user_code']}")
        print("=" * 60 + "\n")
        logger.info(
            "Autorización pendiente — URL: %s  Código: %s",
            flow["verification_uri"],
            flow["user_code"],
        )

        result = app.acquire_token_by_device_flow(flow)  # bloquea hasta autorizar o timeout

    if "access_token" not in result:
        error_desc = result.get("error_description", str(result))
        raise RuntimeError(f"Error obteniendo token OAuth2: {error_desc}")

    # Persistir caché actualizada (guarda el nuevo refresh token si cambió)
    if cache.has_state_changed:
        with open(token_cache_path, "w", encoding="utf-8") as fh:
            fh.write(cache.serialize())
        logger.info("Caché de token OAuth2 guardada en '%s'", token_cache_path)

    # Construir cadena XOAUTH2 en raw bytes.
    # imaplib.authenticate() aplica base64 internamente, así que devolvemos
    # los bytes sin codificar para evitar doble codificación.
    access_token = result["access_token"]
    auth_string = f"user={username}\x01auth=Bearer {access_token}\x01\x01"
    return auth_string.encode()


def get_smtp_oauth2_string(
    username: str,
    client_id: str,
    token_cache_path: str = "token_cache.json",
) -> str:
    """
    Obtiene un access token OAuth2 para SMTP y devuelve la cadena XOAUTH2
    en base64 lista para usar con smtplib.docmd('AUTH', 'XOAUTH2 <string>').

    Reutiliza el mismo token cacheado por get_imap_oauth2_string si existe.
    """
    import base64

    cache = msal.SerializableTokenCache()

    if os.path.exists(token_cache_path):
        with open(token_cache_path, "r", encoding="utf-8") as fh:
            cache.deserialize(fh.read())

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=_AUTHORITY,
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])

    if not result:
        raise RuntimeError(
            "No hay token OAuth2 cacheado para SMTP. "
            "Ejecuta main.py al menos una vez para que el device code flow cachee el token."
        )

    if "access_token" not in result:
        raise RuntimeError(f"Error obteniendo token OAuth2 para SMTP: {result.get('error_description', result)}")

    if cache.has_state_changed:
        with open(token_cache_path, "w", encoding="utf-8") as fh:
            fh.write(cache.serialize())

    access_token = result["access_token"]
    auth_string = f"user={username}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(auth_string.encode()).decode()
