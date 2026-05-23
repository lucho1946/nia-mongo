# ============================================================
# knowledge/document_policy.py
# ============================================================
# RESPONSABILIDAD:
# Política de decisión para saber cuándo NIA debe usar contexto
# documental y cuándo debe usar únicamente catálogo real.
#
# Este módulo NO consulta MongoDB.
# Este módulo NO busca productos.
# Este módulo NO llama OpenAI.
# Este módulo NO responde al usuario.
#
# Solo decide:
# - ¿La consulta necesita soporte documental?
# - ¿Qué tipo de fuente documental conviene usar?
# - ¿La consulta debe ir primero al catálogo real?
#
# Reglas:
# - products_catalog = fuente de verdad para productos.
# - technical_documents = soporte documental/técnico.
# - NIA no debe usar documentos para inventar productos.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEFAULT_DOCUMENT_SOURCE_TYPE = "nia_os"

MAX_REASON_LENGTH = 500


# ============================================================
# PALABRAS CLAVE
# ============================================================

DOCUMENT_EXPLICIT_KEYWORDS = [
    "documento",
    "documentos",
    "archivo",
    "archivos",
    "pdf",
    "manual",
    "ficha",
    "ficha tecnica",
    "ficha técnica",
    "catalogo",
    "catálogo",
    "datasheet",
    "hoja de datos",
    "instructivo",
    "procedimiento",
    "anexo",
    "adjunto",
    "imagen",
    "foto",
    "plano",
    "certificado",
]

NIA_OS_KEYWORDS = [
    "nia os",
    "module_",
    "modulo",
    "módulo",
    "guardrails",
    "no inventar",
    "memoria contextual",
    "vision archivos",
    "visión archivos",
    "motor comercial",
    "motor tecnico",
    "motor técnico",
    "observabilidad",
    "orquestador",
    "cerebro",
    "reglas de nia",
    "reglas",
]

DOCUMENT_ACTION_KEYWORDS = [
    "explica",
    "explícame",
    "que dice",
    "qué dice",
    "resume",
    "resumen",
    "analiza",
    "interpretar",
    "interpreta",
    "leer",
    "lee",
    "revisar",
    "revisa",
    "segun el documento",
    "según el documento",
    "segun la ficha",
    "según la ficha",
    "segun el manual",
    "según el manual",
]

PRODUCT_KEYWORDS = [
    "producto",
    "productos",
    "precio",
    "cotizar",
    "cotizacion",
    "cotización",
    "comprar",
    "disponibilidad",
    "stock",
    "referencia",
    "codigo",
    "código",
    "marca",
    "sensor",
    "motor",
    "plc",
    "variador",
    "valvula",
    "válvula",
    "bomba",
    "torquimetro",
    "torquímetro",
    "manometro",
    "manómetro",
]

TECHNICAL_PRODUCT_KEYWORDS = [
    "voltaje",
    "potencia",
    "hp",
    "kw",
    "bar",
    "psi",
    "rpm",
    "entrada",
    "salida",
    "modbus",
    "ethernet",
    "rs485",
    "rango",
    "presion",
    "presión",
    "temperatura",
    "capacidad",
    "medida",
]

PRODUCT_CODE_PATTERNS = [
    r"\bP[0-9]{4,}[A-Za-z0-9]*\b",
    r"\b[0-9]{6,}\b",
]


# ============================================================
# UTILIDADES
# ============================================================

def normalize_text(text: Any) -> str:
    """
    Normaliza texto:
    - minúsculas
    - sin acentos
    - espacios limpios
    """
    if text is None:
        return ""

    value = str(text).lower().strip()

    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", value)


def contains_any(text: str, keywords: list[str]) -> bool:
    """
    Retorna True si el texto contiene alguna palabra/frase clave.
    """
    text_n = normalize_text(text)

    for keyword in keywords:
        keyword_n = normalize_text(keyword)

        if keyword_n and keyword_n in text_n:
            return True

    return False


def detect_product_code(text: str) -> bool:
    """
    Detecta si el mensaje parece contener un código exacto de producto.
    """
    text_value = str(text or "").strip()

    for pattern in PRODUCT_CODE_PATTERNS:
        if re.search(pattern, text_value, re.IGNORECASE):
            return True

    return False


def _safe_reason(reason: str) -> str:
    """
    Evita razones demasiado largas.
    """
    reason = str(reason or "").strip()

    if len(reason) <= MAX_REASON_LENGTH:
        return reason

    return reason[:MAX_REASON_LENGTH].rstrip()


# ============================================================
# DETECCIÓN PRINCIPAL
# ============================================================

def detect_document_need(
    message: str,
    intent: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Detecta si el mensaje necesita contexto documental.

    Retorna:
    {
        "needs_document_context": bool,
        "source_type": "nia_os" | "manual" | "technical_document" | None,
        "confidence": float,
        "reason": "...",
        "signals": {...}
    }
    """
    context = context or {}
    message_n = normalize_text(message)
    intent_n = normalize_text(intent)

    has_product_code = detect_product_code(message)
    has_document_keyword = contains_any(message_n, DOCUMENT_EXPLICIT_KEYWORDS)
    has_nia_os_keyword = contains_any(message_n, NIA_OS_KEYWORDS)
    has_document_action = contains_any(message_n, DOCUMENT_ACTION_KEYWORDS)
    has_product_keyword = contains_any(message_n, PRODUCT_KEYWORDS)
    has_technical_product_keyword = contains_any(message_n, TECHNICAL_PRODUCT_KEYWORDS)

    has_uploaded_file = bool(
        context.get("archivo_ruta")
        or context.get("archivo_nombre")
        or context.get("file_path")
        or context.get("file_name")
    )

    signals = {
        "has_product_code": has_product_code,
        "has_document_keyword": has_document_keyword,
        "has_nia_os_keyword": has_nia_os_keyword,
        "has_document_action": has_document_action,
        "has_product_keyword": has_product_keyword,
        "has_technical_product_keyword": has_technical_product_keyword,
        "has_uploaded_file": has_uploaded_file,
        "intent": intent,
    }

    # --------------------------------------------------------
    # Regla 1: Si hay archivo adjunto, sí puede requerir documento
    # --------------------------------------------------------
    if has_uploaded_file:
        return {
            "needs_document_context": True,
            "source_type": "uploaded_file",
            "confidence": 0.95,
            "reason": "La consulta contiene o referencia un archivo adjunto.",
            "signals": signals,
        }

    # --------------------------------------------------------
    # Regla 2: Consultas sobre NIA OS o módulos internos
    # --------------------------------------------------------
    if has_nia_os_keyword:
        return {
            "needs_document_context": True,
            "source_type": DEFAULT_DOCUMENT_SOURCE_TYPE,
            "confidence": 0.9,
            "reason": "La consulta menciona reglas, módulos o componentes internos de NIA OS.",
            "signals": signals,
        }

    # --------------------------------------------------------
    # Regla 3: Preguntas explícitas sobre documentos
    # --------------------------------------------------------
    if has_document_keyword and has_document_action:
        return {
            "needs_document_context": True,
            "source_type": "technical_document",
            "confidence": 0.85,
            "reason": "La consulta pide revisar, explicar o interpretar un documento.",
            "signals": signals,
        }

    # --------------------------------------------------------
    # Regla 4: Solo mencionar documento también activa soporte
    # --------------------------------------------------------
    if has_document_keyword and not has_product_code:
        return {
            "needs_document_context": True,
            "source_type": "technical_document",
            "confidence": 0.7,
            "reason": "La consulta menciona documentos, fichas, manuales o archivos.",
            "signals": signals,
        }

    # --------------------------------------------------------
    # Regla 5: Código exacto de producto → catálogo primero
    # --------------------------------------------------------
    if has_product_code:
        return {
            "needs_document_context": False,
            "source_type": None,
            "confidence": 0.95,
            "reason": "La consulta contiene un código de producto; debe usarse catálogo real primero.",
            "signals": signals,
        }

    # --------------------------------------------------------
    # Regla 6: Consulta comercial/técnica de producto → catálogo
    # --------------------------------------------------------
    if has_product_keyword or has_technical_product_keyword:
        return {
            "needs_document_context": False,
            "source_type": None,
            "confidence": 0.85,
            "reason": "La consulta parece ser de producto; debe usarse catálogo real primero.",
            "signals": signals,
        }

    # --------------------------------------------------------
    # Default: no usar documentos
    # --------------------------------------------------------
    return {
        "needs_document_context": False,
        "source_type": None,
        "confidence": 0.5,
        "reason": "No se detectaron señales suficientes para usar contexto documental.",
        "signals": signals,
    }


def should_use_document_context(
    message: str,
    intent: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Retorna solo True/False para uso rápido.
    """
    result = detect_document_need(
        message=message,
        intent=intent,
        context=context,
    )

    return bool(result.get("needs_document_context"))


def get_document_source_type(
    message: str,
    intent: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Retorna el source_type sugerido para retrieval documental.
    """
    result = detect_document_need(
        message=message,
        intent=intent,
        context=context,
    )

    return result.get("source_type")


# ============================================================
# POLÍTICA DE CATÁLOGO
# ============================================================

def should_prioritize_catalog(
    message: str,
    intent: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Decide si el catálogo real debe ir primero.

    Regla:
    - Producto, precio, cotización, código o variables técnicas
      deben ir primero al catálogo.
    """
    context = context or {}
    message_n = normalize_text(message)

    if detect_product_code(message):
        return True

    if contains_any(message_n, PRODUCT_KEYWORDS):
        return True

    if contains_any(message_n, TECHNICAL_PRODUCT_KEYWORDS):
        return True

    if normalize_text(intent) in {"producto", "cotizacion", "cotización", "precio"}:
        return True

    return False


# ============================================================
# FUNCIÓN PRINCIPAL DE POLÍTICA
# ============================================================

def evaluate_document_policy(
    message: str,
    intent: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evalúa la política completa para uso futuro del orquestador.

    Retorna:
    {
        "use_document_context": bool,
        "prioritize_catalog": bool,
        "source_type": str | None,
        "confidence": float,
        "reason": str,
        "signals": {...}
    }
    """
    document_result = detect_document_need(
        message=message,
        intent=intent,
        context=context,
    )

    prioritize_catalog = should_prioritize_catalog(
        message=message,
        intent=intent,
        context=context,
    )

    use_document_context = bool(document_result.get("needs_document_context"))

    # Seguridad:
    # Si la consulta claramente es de producto, el catálogo tiene prioridad.
    # Solo permitir documentos si hay archivo explícito o NIA OS/documento explícito.
    if prioritize_catalog and use_document_context:
        source_type = document_result.get("source_type")

        allowed_document_sources = {
            "uploaded_file",
            "nia_os",
            DEFAULT_DOCUMENT_SOURCE_TYPE,
            "technical_document",
        }

        if source_type not in allowed_document_sources:
            use_document_context = False

    return {
        "use_document_context": use_document_context,
        "prioritize_catalog": prioritize_catalog,
        "source_type": document_result.get("source_type") if use_document_context else None,
        "confidence": document_result.get("confidence", 0.0),
        "reason": _safe_reason(document_result.get("reason", "")),
        "signals": document_result.get("signals", {}),
    }