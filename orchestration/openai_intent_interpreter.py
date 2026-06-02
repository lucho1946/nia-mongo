# ============================================================
# orchestration/openai_intent_interpreter.py
# ============================================================
# RESPONSABILIDAD:
# Interpretar intención comercial usando OpenAI de forma controlada.
#
# Esta capa NO reemplaza:
# - core/intent_router.py
# - NIA OS
# - catálogo real
# - memoria
# - guardrails
#
# Esta capa solo ayuda a convertir lenguaje natural del cliente en:
# - intención candidata
# - query segura para catálogo
# - señales técnicas/comerciales detectadas
# - pregunta sugerida si falta contexto
#
# Regla clave:
# OpenAI NO puede inventar productos, precios, stock ni tiempos.
# ============================================================

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Dict, List

from services.ai import generate_assisted_response, get_openai_config

logger = logging.getLogger(__name__)

AI_INTENT_INTERPRETER_VERSION = "openai_intent_interpreter_v1"


# ============================================================
# UTILIDADES
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte un valor a string seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def _normalize(text: Any) -> str:
    """
    Normaliza texto para reglas fallback.
    """
    text = _safe_str(text).lower()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text).strip()


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Extrae un objeto JSON desde texto devuelto por el modelo.

    El modelo debe responder JSON puro, pero esta función tolera
    que venga algo antes o después.
    """
    raw = _safe_str(text)

    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)

    if not match:
        return {}

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _clean_list(value: Any) -> List[str]:
    """
    Normaliza listas de strings.
    """
    if not isinstance(value, list):
        return []

    cleaned: List[str] = []

    for item in value:
        text = _safe_str(item)
        if text:
            cleaned.append(text)

    return cleaned


def _safe_confidence(value: Any) -> float:
    """
    Normaliza confianza entre 0.0 y 1.0.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    if number < 0:
        return 0.0

    if number > 1:
        return 1.0

    return number


def _valid_intent(value: Any) -> str:
    """
    Limita las intenciones permitidas por el intérprete IA.
    """
    intent = _safe_str(value, "general")

    allowed = {
        "saludo",
        "producto",
        "codigo_producto",
        "cotizacion",
        "comparacion",
        "asesor",
        "postventa",
        "documento",
        "general",
    }

    return intent if intent in allowed else "general"


# ============================================================
# FALLBACK DETERMINÍSTICO
# ============================================================

def fallback_interpret_open_need(message: str) -> Dict[str, Any]:
    """
    Interpretación local sin OpenAI.

    Se usa cuando:
    - OpenAI está apagado.
    - Falta configuración.
    - El modelo falla.
    - La respuesta del modelo no es JSON válido.
    """
    raw = _safe_str(message)
    msg = _normalize(raw)

    product_terms = [
        "sensor",
        "valvula",
        "válvula",
        "motor",
        "variador",
        "plc",
        "hmi",
        "manometro",
        "manómetro",
        "anemometro",
        "anemómetro",
        "velocidad del aire",
        "presion",
        "presión",
        "temperatura",
        "caudal",
        "nivel",
        "ducto",
        "ductos",
        "ventilacion",
        "ventilación",
    ]

    commercial_terms = [
        "comprar",
        "cotizar",
        "cotizacion",
        "cotización",
        "precio",
        "disponibilidad",
        "stock",
    ]

    has_product_signal = any(term in msg for term in product_terms)
    has_commercial_signal = any(term in msg for term in commercial_terms)

    if has_product_signal:
        intent = "producto"
    elif has_commercial_signal:
        intent = "cotizacion"
    else:
        intent = "general"

    normalized_query = raw

    # Mejoramos algunos casos frecuentes sin usar IA.
    if "velocidad del aire" in msg or "ducto" in msg or "ductos" in msg:
        normalized_query = "anemómetro medidor velocidad aire ductos ventilación"

    return {
        "ok": True,
        "source": "deterministic_fallback",
        "version": AI_INTENT_INTERPRETER_VERSION,
        "used_openai": False,
        "intent_candidate": intent,
        "confidence": 0.55 if intent != "general" else 0.2,
        "normalized_query": normalized_query,
        "technical_signals": [],
        "commercial_signals": [
            term for term in commercial_terms if term in msg
        ],
        "needs_catalog_search": intent in ["producto", "cotizacion"],
        "should_ask": intent == "general",
        "suggested_question": (
            "¿Qué producto industrial necesitas o qué aplicación quieres resolver?"
            if intent == "general"
            else ""
        ),
        "reason": "fallback_without_openai",
    }


# ============================================================
# INTERPRETACIÓN CON OPENAI
# ============================================================

def build_openai_intent_context() -> str:
    """
    Contexto seguro para que OpenAI interprete intención.

    No contiene secretos.
    No contiene catálogo completo.
    No contiene reglas internas sensibles.
    """
    return (
        "VIA Industrial vende equipos industriales, instrumentación, "
        "medición, automatización, sensores, válvulas, motores, variadores, "
        "PLCs, HMIs, manómetros, transmisores, herramientas y equipos relacionados.\n\n"
        "Debes devolver SOLO un JSON válido con esta estructura:\n"
        "{\n"
        '  "intent_candidate": "producto|codigo_producto|cotizacion|comparacion|asesor|postventa|documento|saludo|general",\n'
        '  "confidence": 0.0,\n'
        '  "normalized_query": "consulta corta para buscar en catálogo",\n'
        '  "technical_signals": ["señales técnicas detectadas"],\n'
        '  "commercial_signals": ["señales comerciales detectadas"],\n'
        '  "needs_catalog_search": true,\n'
        '  "should_ask": false,\n'
        '  "suggested_question": "máximo una pregunta si falta información",\n'
        '  "reason": "explicación breve"\n'
        "}\n\n"
        "Reglas:\n"
        "- No inventes productos.\n"
        "- No inventes precios.\n"
        "- No inventes disponibilidad.\n"
        "- No inventes tiempos de entrega.\n"
        "- Si el cliente describe una aplicación, convierte eso en una query útil para catálogo.\n"
        "- Si el cliente menciona velocidad de aire, ductos o ventilación, la query debe apuntar a anemómetro/medición de aire.\n"
        "- Si falta información, sugiere máximo una pregunta.\n"
        "- No respondas al cliente; solo devuelve JSON."
    )


def interpret_open_customer_need(
    message: str,
    *,
    session_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Interpreta una necesidad abierta del cliente usando OpenAI si está habilitado.

    Esta función NO busca productos.
    Esta función NO responde al cliente.
    Esta función NO crea oportunidades.

    Solo devuelve una interpretación estructurada para que el orquestador
    decida el siguiente paso.
    """
    raw_message = _safe_str(message)

    if not raw_message:
        return {
            "ok": False,
            "source": "openai_intent_interpreter",
            "version": AI_INTENT_INTERPRETER_VERSION,
            "used_openai": False,
            "intent_candidate": "general",
            "confidence": 0.0,
            "normalized_query": "",
            "technical_signals": [],
            "commercial_signals": [],
            "needs_catalog_search": False,
            "should_ask": True,
            "suggested_question": "¿Qué producto industrial necesitas?",
            "reason": "empty_message",
        }

    config = get_openai_config()

    # Si OpenAI no está listo, usamos fallback determinístico.
    if not config.get("ready"):
        result = fallback_interpret_open_need(raw_message)
        result["openai_config"] = {
            "enabled": config.get("enabled"),
            "ready": config.get("ready"),
            "model": config.get("model"),
            "api_key_configured": config.get("api_key_configured"),
            "missing": config.get("missing"),
        }
        return result

    safe_context = build_openai_intent_context()

    if session_context:
        active_product = session_context.get("codigo_producto") or session_context.get("referencia")
        if active_product:
            safe_context += f"\n\nContexto de sesión permitido: producto activo {active_product}."

    fallback = json.dumps(
        fallback_interpret_open_need(raw_message),
        ensure_ascii=False,
    )

    ai_result = generate_assisted_response(
        user_message=raw_message,
        safe_context=safe_context,
        task="interpretar_intencion_comercial_para_catalogo",
        fallback_response=fallback,
    )

    if not ai_result.get("ok"):
        fallback_result = fallback_interpret_open_need(raw_message)
        fallback_result["source"] = "fallback_after_openai_unavailable"
        fallback_result["openai_result"] = {
            "ok": ai_result.get("ok"),
            "used_openai": ai_result.get("used_openai"),
            "reason": ai_result.get("reason"),
        }
        return fallback_result

    parsed = _extract_json_object(ai_result.get("response", ""))

    if not parsed:
        fallback_result = fallback_interpret_open_need(raw_message)
        fallback_result["source"] = "fallback_after_invalid_openai_json"
        fallback_result["openai_result"] = {
            "ok": ai_result.get("ok"),
            "used_openai": ai_result.get("used_openai"),
            "reason": "invalid_json",
            "raw_response": ai_result.get("response", "")[:500],
        }
        return fallback_result

    intent = _valid_intent(parsed.get("intent_candidate"))
    confidence = _safe_confidence(parsed.get("confidence"))

    normalized_query = _safe_str(parsed.get("normalized_query"), raw_message)

    result = {
        "ok": True,
        "source": "openai",
        "version": AI_INTENT_INTERPRETER_VERSION,
        "used_openai": True,
        "intent_candidate": intent,
        "confidence": confidence,
        "normalized_query": normalized_query,
        "technical_signals": _clean_list(parsed.get("technical_signals")),
        "commercial_signals": _clean_list(parsed.get("commercial_signals")),
        "needs_catalog_search": bool(parsed.get("needs_catalog_search")),
        "should_ask": bool(parsed.get("should_ask")),
        "suggested_question": _safe_str(parsed.get("suggested_question")),
        "reason": _safe_str(parsed.get("reason")),
        "model": ai_result.get("model"),
        "response_id": ai_result.get("response_id"),
        "usage": ai_result.get("usage", {}),
    }

    # Regla de seguridad: si dice buscar pero no hay query, no buscamos.
    if result["needs_catalog_search"] and not result["normalized_query"]:
        result["needs_catalog_search"] = False
        result["should_ask"] = True
        result["suggested_question"] = "¿Me confirmas qué producto o aplicación necesitas?"

    return result