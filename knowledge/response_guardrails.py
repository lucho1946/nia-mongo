# ============================================================
# knowledge/response_guardrails.py
# ============================================================
# RESPONSABILIDAD:
# Validar respuestas finales de NIA antes de entregarlas al usuario.
#
# Este módulo hace parte de la integración progresiva de NIA OS.
# Primera fase activa:
# - aplicar reglas de no inventar;
# - detectar frases riesgosas;
# - marcar metadata de seguridad;
# - no bloquear todavía el flujo principal.
#
# Este módulo NO:
# - busca productos;
# - consulta Mongo;
# - decide intención;
# - genera respuestas comerciales;
# - modifica memoria;
# - reemplaza el response_engine.
#
# Uso esperado futuro:
# response_engine / orchestrator
#   -> genera respuesta
#   -> validate_response_guardrails(...)
#   -> adjunta metadata / ajusta si hay riesgo
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


# ============================================================
# CONFIGURACIÓN
# ============================================================

GUARDRAIL_VERSION = "response_guardrails_v1"

# Frases que suelen indicar promesa no verificada.
# No significa que siempre sean malas, pero deben marcarse como riesgo.
RISKY_PROMISE_PATTERNS = [
    "te garantizo",
    "garantizado",
    "garantizada",
    "stock asegurado",
    "disponibilidad asegurada",
    "entrega garantizada",
    "entrega asegurada",
    "precio fijo",
    "precio garantizado",
    "descuento garantizado",
    "compatibilidad garantizada",
    "100% compatible",
    "totalmente compatible",
    "sin confirmar",
]

# Datos comerciales que NIA no debe inventar.
SENSITIVE_COMMERCIAL_TOPICS = [
    "precio",
    "precios",
    "stock",
    "disponibilidad",
    "inventario",
    "entrega",
    "tiempo de entrega",
    "flete",
    "descuento",
    "compatibilidad",
    "garantia",
    "garantía",
]

# Señales aceptables cuando NIA evita inventar.
SAFE_UNCERTAINTY_PATTERNS = [
    "consultar",
    "consultarnos",
    "validar",
    "confirmar",
    "revisar",
    "no tengo suficiente certeza",
    "no hay suficiente certeza",
    "información confirmada",
    "catalogo real",
    "catálogo real",
    "asesor",
]


# ============================================================
# UTILIDADES
# ============================================================

def normalize_text(value: Any) -> str:
    """
    Normaliza texto para comparaciones robustas:
    - convierte a string;
    - pasa a minúsculas;
    - elimina tildes;
    - limpia espacios.
    """
    if value is None:
        return ""

    text = str(value).lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text)


def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte valores a string seguro.
    """
    if value is None:
        return default

    try:
        return str(value).strip()
    except Exception:
        return default


def _contains_any(text: str, patterns: List[str]) -> bool:
    """
    Retorna True si el texto contiene alguno de los patrones.
    """
    text_n = normalize_text(text)

    for pattern in patterns:
        pattern_n = normalize_text(pattern)

        if pattern_n and pattern_n in text_n:
            return True

    return False


def _find_matches(text: str, patterns: List[str]) -> List[str]:
    """
    Devuelve los patrones encontrados dentro del texto.
    """
    text_n = normalize_text(text)
    matches: List[str] = []

    for pattern in patterns:
        pattern_n = normalize_text(pattern)

        if pattern_n and pattern_n in text_n:
            matches.append(pattern)

    return matches


def _response_mentions_sensitive_commercial_topic(response_text: str) -> bool:
    """
    Detecta si la respuesta habla de datos comerciales sensibles.
    """
    return _contains_any(response_text, SENSITIVE_COMMERCIAL_TOPICS)


def _response_uses_safe_uncertainty(response_text: str) -> bool:
    """
    Detecta si la respuesta usa lenguaje seguro de validación/confirmación.
    """
    return _contains_any(response_text, SAFE_UNCERTAINTY_PATTERNS)


# ============================================================
# VALIDACIÓN PRINCIPAL
# ============================================================

def validate_response_guardrails(
    response_text: Any,
    *,
    context: Optional[Dict[str, Any]] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    source: str = "response_engine",
) -> Dict[str, Any]:
    """
    Valida una respuesta de NIA contra guardrails básicos.

    Parámetros:
    - response_text: texto que NIA va a entregar al usuario.
    - context: contexto conversacional opcional.
    - products: productos usados como base, si aplica.
    - source: componente que generó la respuesta.

    Retorna metadata segura:

    {
      "ok": bool,
      "version": "...",
      "source": "...",
      "risk_level": "none|low|medium|high",
      "flags": [...],
      "recommendation": "allow|review|rewrite"
    }

    En esta fase NO reescribe automáticamente la respuesta.
    Solo diagnostica.
    """
    context = context or {}
    products = products or []

    text = _safe_str(response_text)
    normalized = normalize_text(text)

    flags: List[str] = []
    risky_matches = _find_matches(text, RISKY_PROMISE_PATTERNS)

    if not text:
        flags.append("empty_response")

    if risky_matches:
        flags.append("risky_promise_language")

    mentions_sensitive_topic = _response_mentions_sensitive_commercial_topic(text)
    uses_safe_uncertainty = _response_uses_safe_uncertainty(text)

    # Si habla de precio/stock/entrega/compatibilidad pero no hay productos
    # ni lenguaje de validación, se marca para revisión.
    if mentions_sensitive_topic and not products and not uses_safe_uncertainty:
        flags.append("sensitive_commercial_claim_without_product_source")

    # Si menciona producto exacto pero no hay productos asociados,
    # se marca como posible respuesta no respaldada.
    if (
        "producto exacto" in normalized
        and not products
    ):
        flags.append("exact_product_claim_without_products")

    # Si hay productos, asumimos que la respuesta puede estar respaldada
    # por catálogo, pero igual marcamos promesas absolutas si existen.
    product_count = len(products)

    if "risky_promise_language" in flags:
        risk_level = "high"
        recommendation = "review"
    elif flags:
        risk_level = "medium"
        recommendation = "review"
    else:
        risk_level = "none"
        recommendation = "allow"

    return {
        "ok": len(flags) == 0,
        "version": GUARDRAIL_VERSION,
        "source": source,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "flags": flags,
        "risky_matches": risky_matches,
        "product_count": product_count,
        "mentions_sensitive_commercial_topic": mentions_sensitive_topic,
        "uses_safe_uncertainty": uses_safe_uncertainty,
    }


def apply_response_guardrails(
    response_payload: Dict[str, Any],
    *,
    source: str = "response_engine",
) -> Dict[str, Any]:
    """
    Aplica validación de guardrails a un payload de respuesta.

    Esta función NO bloquea ni reescribe todavía.
    Solo adjunta metadata en:

    response_payload["response_guardrails"]

    Acepta payloads tipo:
    {
      "response": "...",
      "cards": [...]
    }

    o:
    {
      "respuesta": "...",
      "productos": [...]
    }
    """
    if not isinstance(response_payload, dict):
        return {
            "response": "",
            "response_guardrails": validate_response_guardrails(
                "",
                source=source,
            ),
        }

    response_text = (
        response_payload.get("response")
        or response_payload.get("respuesta")
        or ""
    )

    products = []

    if isinstance(response_payload.get("cards"), list):
        products = response_payload.get("cards") or []
    elif isinstance(response_payload.get("productos"), list):
        products = response_payload.get("productos") or []

    guardrail_result = validate_response_guardrails(
        response_text=response_text,
        context=response_payload.get("context") or {},
        products=products,
        source=source,
    )

    response_payload["response_guardrails"] = guardrail_result

    return response_payload


# ============================================================
# HELPERS DE DECISIÓN
# ============================================================

def should_review_response(response_payload: Dict[str, Any]) -> bool:
    """
    Retorna True si la respuesta debería pasar por revisión
    antes de enviarse en una integración futura.
    """
    if not isinstance(response_payload, dict):
        return True

    guardrails = response_payload.get("response_guardrails")

    if not isinstance(guardrails, dict):
        response_payload = apply_response_guardrails(response_payload)
        guardrails = response_payload.get("response_guardrails", {})

    return guardrails.get("recommendation") == "review"


def is_response_allowed(response_payload: Dict[str, Any]) -> bool:
    """
    Retorna True si la respuesta no presenta riesgos detectados.
    """
    if not isinstance(response_payload, dict):
        return False

    guardrails = response_payload.get("response_guardrails")

    if not isinstance(guardrails, dict):
        response_payload = apply_response_guardrails(response_payload)
        guardrails = response_payload.get("response_guardrails", {})

    return guardrails.get("recommendation") == "allow"