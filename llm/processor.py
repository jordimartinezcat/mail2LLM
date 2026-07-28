import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime

import requests

from config.loader import LLMConfig

logger = logging.getLogger("processMail")


def _compute_ref(email_date_str: str) -> tuple[str, int]:
    """
    Devuelve (YYYY-MM-01 del mes anterior al correo, año de ese mes anterior).
    Si no se puede parsear la fecha del correo, usa el mes anterior a hoy.
    """
    try:
        dt = parsedate_to_datetime(email_date_str)
        if dt.month == 1:
            return f"{dt.year - 1}-12-01", dt.year - 1
        else:
            return f"{dt.year}-{dt.month - 1:02d}-01", dt.year
    except Exception:
        today = date.today()
        if today.month == 1:
            return f"{today.year - 1}-12-01", today.year - 1
        else:
            return f"{today.year}-{today.month - 1:02d}-01", today.year

_PROMPT_TEMPLATE = """\
CRITICAL: Extract EXACTLY the values from the HTML table. Do NOT invent or modify any data.

**TASK:**
Read the HTML content below and extract ALL data rows from the table (skip header row).

**STEP 1 - EXTRACT PERIOD/DATE:**
Look for period indicator in the HTML:
- Search for: "Període:", "Periodo:", "Període de facturació:", or similar
- Extract month name and year (e.g., "Juliol 2026", "Gener 2025")
- Convert to YYYY-MM-01 format using this mapping:
  * Gener/Enero/January → 01
  * Febrer/Febrero/February → 02
  * Març/Marzo/March → 03
  * Abril/April → 04
  * Maig/Mayo/May → 05
  * Juny/Junio/June → 06
  * Juliol/Julio/July → 07
  * Agost/Agosto/August → 08
  * Setembre/Septiembre/September → 09
  * Octubre/October → 10
  * Novembre/Noviembre/November → 11
  * Desembre/Diciembre/December → 12
- If NO period found in text → return null for fecha

**STEP 2 - EXTRACT TABLE DATA:**
HTML TABLE STRUCTURE:
- Column 1: Client ID → format "CLxxxxx-idtag" OR "CLxxxxx" only
- Column 2: Company name
- Column 3: Consumption value (numeric)

**EXTRACTION RULES:**
1. Column 1 (ID):
   - If contains "-": Split → id_bcentral (before "-"), idtag (after "-")
   - If NO "-": Only id_bcentral, idtag=null
2. Column 2: Copy company name exactly as written
3. Column 3: Extract numeric value only
4. fecha: Use the date extracted in STEP 1 (same for all rows)

**RETURN JSON ARRAY:**
[
  {{"id_bcentral": "CLxxxxx", "idtag": 12345, "empresa": "Company Name", "valor": 999, "unidades": "m3", "fecha": "2026-07-01"}}
]

**HTML TO PROCESS:**
{body}

**CRITICAL:** Extract from the HTML above, NOT from examples. Return [] if no data rows exist.

Return ONLY the JSON array, no explanation. If no valid data rows found, return [].

HTML Table:
{{body}}
"""


@dataclass
class Consumption:
    fecha: str | None
    empresa: str | None
    valor: float | None
    unidades: str = "m3"
    id_bcentral: str | None = None  # ID de la empresa (ej: CL00091), extraído del formato "CLxxxxx-idtag"
    idtag: int | None = None  # ✨ idTag de la señal, extraído del formato "CLxxxxx-idtag" (inserción directa en BD)
    fecha_inferida: bool = False  # True si la fecha s'ha inferit del correu (no estava al cos)

    def to_dict(self) -> dict:
        return {
            "fecha": self.fecha,
            "empresa": self.empresa,
            "valor": self.valor,
            "unidades": self.unidades,
            "id_bcentral": self.id_bcentral,
            "idtag": self.idtag,
        }


def extract_consumption(
    body: str, 
    config: LLMConfig, 
    email_date: str = "",
    pdf_contents: list[str] | None = None,
    companies: list[tuple[str, str]] | None = None,
    sender: str = "",
    subject: str = ""
) -> list["Consumption"] | None:
    """
    Envía el cuerpo del correo y contenido de PDFs adjuntos al LLM y extrae los datos de consumo.
    
    Args:
        body: Cuerpo del email en texto plano
        config: Configuración del LLM
        email_date: Cabecera Date: del correo (RFC 2822), usada para calcular la fecha de referencia
        pdf_contents: Lista de contenidos de PDFs adjuntos extraídos
        companies: Lista de (id, nombre) de empresas registradas para ayudar al LLM
        sender: Remitente del email (para ayudar a identificar la empresa)
        subject: Asunto del email (para ayudar a identificar la empresa)
    
    Returns:
        Lista de Consumption (puede ser vacía), o None si hay error
    """
    ref_date, ref_year = _compute_ref(email_date)
    
    # Combinar cuerpo del email con contenido de PDFs
    combined_content = body.strip()
    if pdf_contents:
        combined_content += "\n\n" + "\n\n═══════════════════════════════════\n\n".join(pdf_contents)
    
    # 🔍 DEBUG: Log del HTML COMPLETO enviado al LLM
    logger.info("="*80)
    logger.info("🔍 HTML COMPLETO ENVIADO AL LLM:")
    logger.info("="*80)
    logger.info("%s", combined_content)
    logger.info("="*80)
    logger.info("🔍 FIN HTML - Longitud total: %d caracteres", len(combined_content))
    logger.info("="*80)
    
    # Formatear lista de empresas para el prompt (limitar a primeras 50 para no saturar)
    companies_text = "No company list provided."
    if companies:
        companies_sample = companies[:50]  # Primeras 50 empresas
        companies_lines = [f"- {nombre} (ID: {id_})" for id_, nombre in companies_sample]
        if len(companies) > 50:
            companies_lines.append(f"... and {len(companies) - 50} more companies")
        companies_text = "\n".join(companies_lines)
    
    prompt = _PROMPT_TEMPLATE.format(body=combined_content)
    
    # Log: verificar contexto enviado al LLM
    logger.info("  Contexto enviado al LLM → From: %s | Subject: %s", 
                sender or "Unknown", subject or "No subject")

    _RESPONSE_SCHEMA = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "fecha":       {"type": ["string", "null"], "description": "ISO 8601 date (YYYY-MM-DD) or null"},
                "empresa":     {"type": ["string", "null"], "description": "Company name or identifier"},
                "id_bcentral": {"type": ["string", "null"], "description": "Company ID (CLxxxxx format) or null"},
                "idtag":       {"type": ["integer", "null"], "description": "Signal idTag from HTML id or title attribute"},
                "valor":       {"type": ["number", "null"], "description": "Consumption in cubic meters"},
                "unidades":    {"type": "string", "enum": ["m3"]},
            },
            "required": ["fecha", "empresa", "id_bcentral", "valor", "unidades"],
        },
    }

    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.1,
        "top_p": 0.9,
        "max_tokens": 2048,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "consumptions",
                "strict": True,
                "schema": _RESPONSE_SCHEMA,
            },
        },
    }

    is_azure = config.provider.lower() == "azure_openai"
    is_huggingface = config.provider.lower() == "huggingface"

    if is_azure:
        url = f"{config.endpoint}/chat/completions?api-version={config.api_version}"
        headers = {"api-key": config.api_key, "Content-Type": "application/json"}
        # Los modelos de razonamiento (o1, o3, o4-mini) no aceptan temperature/top_p
        # y usan max_completion_tokens en lugar de max_tokens
        payload.pop("model", None)
        payload.pop("chat_template_kwargs", None)
        payload.pop("temperature", None)
        payload.pop("top_p", None)
        payload.pop("max_tokens", None)  # Azure o4-mini: sin límite de tokens de salida
        payload.pop("response_format", None)  # Azure usa su propia API de structured output
    elif is_huggingface:
        url = f"{config.endpoint}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
        # HF Inference API no acepta parámetros específicos de Ollama
        payload.pop("chat_template_kwargs", None)
        payload.pop("response_format", None)  # HF no garantiza soporte de json_schema
    else:
        url = f"{config.endpoint}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=180,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        logger.error(
            "No se puede conectar con el LLM en %s. "
            "¿Está el servidor arrancado?",
            url,
        )
        return None
    except requests.exceptions.Timeout:
        logger.error("Timeout esperando respuesta del LLM (>180s)")
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("Error en la llamada al LLM: %s", exc)
        return None

    full_response = response.json()
    message = full_response["choices"][0]["message"]
    raw_content = message.get("content", "").strip()

    if not raw_content:
        raw_content = message.get("reasoning_content", "").strip()

    if not raw_content:
        logger.error("Respuesta LLM vacía. finish_reason=%s | message=%s",
                     full_response["choices"][0].get("finish_reason"), message)
        return None

    logger.debug("Respuesta LLM raw: %s", raw_content)

    consumptions = _parse_response(raw_content)

    # Fallback Python: si el LLM devuelve fecha=null, aplicar la fecha de referencia
    if consumptions:
        for c in consumptions:
            if c.fecha is None:
                logger.info(
                    "  Data no indicada al correu — s'assigna data de referència: %s (empresa=%s)",
                    ref_date, c.empresa,
                )
                c.fecha = ref_date
                c.fecha_inferida = True

    return consumptions


def _parse_response(raw: str) -> list["Consumption"] | None:
    """Extrae el array JSON de la respuesta del LLM y construye objetos Consumption."""
    # Extraer contenido de bloques <think> como fallback antes de eliminarlos
    think_content = ""
    think_match = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    if think_match:
        think_content = think_match.group(1).strip()

    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    if not raw and think_content:
        raw = think_content

    # Buscar el array JSON: primero en bloques ```json```, luego directamente
    array_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
    if array_match:
        json_str = array_match.group(1)
    else:
        bracket_match = re.search(r"\[.*\]", raw, re.DOTALL)
        json_str = bracket_match.group(0) if bracket_match else None

    if json_str:
        try:
            items = json.loads(json_str)
            if isinstance(items, list):
                return [_build_consumption(item) for item in items if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass

    # Fallback: buscar objetos JSON individuales (respuesta mal formateada)
    candidates = list(re.finditer(r"\{[^{}]*\}", raw, re.DOTALL))
    consumptions = []
    for match in candidates:
        try:
            item = json.loads(match.group(0))
            if isinstance(item, dict) and "unidades" in item:
                consumptions.append(_build_consumption(item))
        except json.JSONDecodeError:
            continue

    if consumptions:
        return consumptions

    logger.error("La respuesta del LLM no contiene JSON válido | Raw: %s", raw[:500])
    return None


def _build_consumption(data: dict) -> "Consumption":
    """Construye un Consumption desde un dict, normalizando el campo valor."""
    valor = data.get("valor")
    if valor is not None:
        try:
            valor = float(str(valor).replace(",", "."))
        except (ValueError, TypeError):
            logger.warning("El campo 'valor' no es numérico: %s", valor)
            valor = None
    return Consumption(
        fecha=data.get("fecha"),
        empresa=data.get("empresa"),
        valor=valor,
        unidades=data.get("unidades", "m3"),
        id_bcentral=data.get("id_bcentral"),
        idtag=data.get("idtag"),
    )
