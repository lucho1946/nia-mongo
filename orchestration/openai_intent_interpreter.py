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
# - contexto funcional de la necesidad
# - pregunta sugerida si falta contexto
#
# Regla clave:
# OpenAI NO puede inventar productos, precios, stock ni tiempos.
# Los libros industriales solo apoyan la interpretación técnica.
# ============================================================

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Dict, List

from knowledge.nia_os.runtime_policy_loader import build_openai_runtime_policy_prompt
from retrieval.industrial_knowledge_retriever import build_industrial_context_for_prompt
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


def _detect_exact_code(text: Any) -> str:
    """
    Detecta códigos exactos tipo VIA.

    Este helper es permitido en fallback porque no interpreta semántica:
    solo detecta identificadores explícitos escritos por el usuario.

    Ejemplos válidos:
    - 300203
    - P382169
    """
    normalized = _safe_str(text).upper()

    match = re.search(r"\b(P\d{5,}|\d{6,})\b", normalized)

    if not match:
        return ""

    return match.group(1)


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


def _empty_industrial_context(reason: str = "industrial_context_not_used") -> Dict[str, Any]:
    """
    Metadata estándar cuando no se usa contexto industrial.
    """
    return {
        "used": False,
        "result_count": 0,
        "reason": reason,
    }


# ============================================================
# FALLBACK CONSERVADOR
# ============================================================

def fallback_interpret_open_need(message: str) -> Dict[str, Any]:
    """
    Fallback conservador sin OpenAI.

    Responsabilidad:
    - NO reemplaza a OpenAI.
    - NO interpreta familias.
    - NO interpreta marcas.
    - NO inventa líneas de catálogo.
    - NO genera términos técnicos inventados.
    - Solo cubre casos seguros:
      1. mensaje vacío/general;
      2. código exacto;
      3. necesidad abierta sin OpenAI -> pedir aclaración.

    La interpretación semántica real debe hacerla OpenAI cuando esté disponible.
    El catálogo real decide productos.
    """
    raw = _safe_str(message)
    msg = _normalize(raw)

    detected_code = _detect_exact_code(raw)

    # --------------------------------------------------------
    # Caso 1: mensaje vacío
    # --------------------------------------------------------
    if not msg:
        return {
            "ok": True,
            "source": "conservative_fallback",
            "version": AI_INTENT_INTERPRETER_VERSION,
            "used_openai": False,
            "intent_candidate": "general",
            "confidence": 0.2,
            "normalized_query": "",
            "need_type": "general",
            "required_action": "",
            "required_target": "",
            "application_context": "",
            "detected_code": "",
            "detected_reference": "",
            "semantic_profile": "",
            "family_hint": "",
            "subtype_hint": "",
            "catalog_line_hints": {},
            "product_need_terms": [],
            "description_short_terms": [],
            "description_long_terms": [],
            "positive_terms": [],
            "negative_terms": [],
            "technical_signals": [],
            "commercial_signals": [],
            "needs_catalog_search": False,
            "should_ask": True,
            "suggested_question": "¿Qué producto industrial necesitas o qué aplicación quieres resolver?",
            "decision_reason": "Mensaje vacío o sin información suficiente.",
            "reason": "empty_message_conservative_fallback",
            "industrial_context": _empty_industrial_context("fallback_without_openai"),
        }

    # --------------------------------------------------------
    # Caso 2: código exacto
    # --------------------------------------------------------
    if detected_code:
        return {
            "ok": True,
            "source": "conservative_fallback",
            "version": AI_INTENT_INTERPRETER_VERSION,
            "used_openai": False,
            "intent_candidate": "codigo_producto",
            "confidence": 0.95,
            "normalized_query": detected_code,
            "need_type": "codigo_producto",
            "required_action": "consultar",
            "required_target": "codigo_producto",
            "application_context": "",
            "detected_code": detected_code,
            "detected_reference": "",
            "semantic_profile": "",
            "family_hint": "",
            "subtype_hint": "",
            "catalog_line_hints": {},
            "product_need_terms": [detected_code],
            "description_short_terms": [],
            "description_long_terms": [],
            "positive_terms": [],
            "negative_terms": [],
            "technical_signals": [],
            "commercial_signals": [],
            "needs_catalog_search": True,
            "should_ask": False,
            "suggested_question": "",
            "decision_reason": "El usuario escribió un código exacto; NIA debe consultar catálogo real.",
            "reason": "exact_code_detected_conservative_fallback",
            "industrial_context": _empty_industrial_context("fallback_exact_code_without_books"),
        }

    # --------------------------------------------------------
    # Caso 3: necesidad abierta sin OpenAI
    # --------------------------------------------------------
    # No intentamos entender semántica con listas manuales.
    # Pedimos una aclaración mínima para evitar búsquedas malas.
    # --------------------------------------------------------
    return {
        "ok": True,
        "source": "conservative_fallback",
        "version": AI_INTENT_INTERPRETER_VERSION,
        "used_openai": False,
        "intent_candidate": "general",
        "confidence": 0.35,
        "normalized_query": "",
        "need_type": "general",
        "required_action": "",
        "required_target": "",
        "application_context": "",
        "detected_code": "",
        "detected_reference": "",
        "semantic_profile": "",
        "family_hint": "",
        "subtype_hint": "",
        "catalog_line_hints": {},
        "product_need_terms": [],
        "description_short_terms": [],
        "description_long_terms": [],
        "positive_terms": [],
        "negative_terms": [],
        "technical_signals": [],
        "commercial_signals": [],
        "needs_catalog_search": False,
        "should_ask": True,
        "suggested_question": "¿Qué producto industrial necesitas o qué aplicación quieres resolver?",
        "decision_reason": "OpenAI no está disponible y el mensaje requiere interpretación semántica; se pide aclaración para evitar una búsqueda incorrecta.",
        "reason": "open_need_requires_openai_or_clarification",
        "industrial_context": _empty_industrial_context("fallback_open_need_without_openai"),
    }


# ============================================================
# CONTEXTO INDUSTRIAL DESDE LIBROS
# ============================================================

def build_safe_industrial_context_for_openai(message: str) -> Dict[str, Any]:
    """
    Construye contexto técnico industrial desde libros para apoyar
    la interpretación semántica de OpenAI.

    Reglas:
    - No reemplaza catálogo.
    - No recomienda productos.
    - No inventa referencias.
    - No confirma precio, stock ni disponibilidad.
    - Si falla, no rompe el flujo: devuelve contexto vacío.
    """
    try:
        result = build_industrial_context_for_prompt(
            query=message,
            max_results=3,
            max_chars=2500,
        )

        if not result.get("ok"):
            return {
                "ok": False,
                "context": "",
                "result_count": 0,
                "reason": "industrial_context_not_ok",
            }

        context = str(result.get("context") or "").strip()

        if not context:
            return {
                "ok": True,
                "context": "",
                "result_count": 0,
                "reason": "industrial_context_empty",
            }

        return {
            "ok": True,
            "context": context,
            "result_count": int(result.get("result_count") or 0),
            "reason": "industrial_context_ready",
        }

    except Exception as exc:
        logger.warning("No se pudo construir contexto industrial. Error=%s", exc)
        return {
            "ok": False,
            "context": "",
            "result_count": 0,
            "reason": f"industrial_context_error: {exc}",
        }


# ============================================================
# INTERPRETACIÓN CON OPENAI
# ============================================================

def build_openai_intent_context() -> str:
    """
    Construye el contexto seguro para que OpenAI interprete intención.

    Las reglas runtime se cargan desde NIA OS mediante:
    knowledge/nia_os/runtime_policy_loader.py

    Esto evita duplicar la política oficial dentro del código.
    """
    runtime_policy = build_openai_runtime_policy_prompt()

    return (
        "Eres el motor de interpretación semántica de NIA para VIA Industrial.\n"
        "Tu tarea NO es responder al cliente y NO es recomendar productos.\n"
        "Tu única tarea es interpretar intención, necesidad técnica y señales comerciales "
        "para que NIA consulte el catálogo real.\n\n"

        f"{runtime_policy}\n\n"

        "INSTRUCCIONES OPERATIVAS PARA ESTA RESPUESTA:\n"
        "- Si el cliente describe una aplicación, genera una normalized_query corta "
        "derivada del mensaje del cliente.\n"
        "- Extrae la necesidad funcional en tres partes: required_action, required_target "
        "y application_context.\n"
        "- required_action debe describir qué quiere hacer el cliente, por ejemplo: "
        "medir, controlar, detectar, mover, regular, cortar, filtrar, transmitir, "
        "registrar, dosificar o consultar.\n"
        "- required_target debe describir sobre qué variable, objeto o proceso aplica "
        "la acción, por ejemplo: velocidad del aire, presión, temperatura, presencia, "
        "nivel, caudal, motor, fluido, carga o señal.\n"
        "- application_context debe describir el entorno o uso mencionado, por ejemplo: "
        "ductos, ventilación, línea de producción, tanque, tubería, tablero, motor, "
        "laboratorio o campo.\n"
        "- Si falta información mínima, marca should_ask=true y propone máximo una pregunta.\n"
        "- Si hay intención suficiente para buscar, marca needs_catalog_search=true.\n"
        "- El catálogo real decidirá productos usando CODIGO, REFERENCIA, MARCA_LET, "
        "NIVEL_0 a NIVEL_4, DESCRIPCION_CORTA_PRE y DESCRIPCION_LARGA_PRE.\n\n"

        "Devuelve SOLO un JSON válido con esta estructura:\n"
        "{\n"
        '  "intent_candidate": "producto|codigo_producto|cotizacion|comparacion|asesor|postventa|documento|saludo|general",\n'
        '  "confidence": 0.0,\n'
        '  "normalized_query": "consulta corta derivada del mensaje para buscar en catálogo real",\n'
        '  "need_type": "busqueda_producto|busqueda_por_aplicacion|precio|disponibilidad|compra|soporte|general",\n'
        '  "required_action": "acción funcional requerida por el cliente",\n'
        '  "required_target": "variable, producto, proceso u objeto sobre el que aplica la acción",\n'
        '  "application_context": "entorno, aplicación o contexto de uso mencionado",\n'
        '  "detected_code": "",\n'
        '  "detected_reference": "",\n'
        '  "product_need_terms": ["términos principales derivados del mensaje del usuario"],\n'
        '  "technical_signals": ["señales técnicas mencionadas o claramente implicadas"],\n'
        '  "commercial_signals": ["precio|cotizar|comprar|stock|disponibilidad si aplica"],\n'
        '  "needs_catalog_search": true,\n'
        '  "should_ask": false,\n'
        '  "suggested_question": "máximo una pregunta si falta información",\n'
        '  "decision_reason": "explicación breve de la decisión"\n'
        "}\n\n"

        "No incluyas campos adicionales como family_hint, familia, recommended_product, "
        "price, stock, delivery_time, nivel_0_value, nivel_1_value, nivel_2_value, "
        "nivel_3_value o nivel_4_value."
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
            "need_type": "general",
            "required_action": "",
            "required_target": "",
            "application_context": "",
            "detected_code": "",
            "detected_reference": "",
            "semantic_profile": "",
            "family_hint": "",
            "subtype_hint": "",
            "catalog_line_hints": {},
            "description_short_terms": [],
            "description_long_terms": [],
            "positive_terms": [],
            "negative_terms": [],
            "product_need_terms": [],
            "technical_signals": [],
            "commercial_signals": [],
            "needs_catalog_search": False,
            "should_ask": True,
            "suggested_question": "¿Qué producto industrial necesitas?",
            "decision_reason": "empty_message",
            "reason": "empty_message",
            "industrial_context": _empty_industrial_context("empty_message"),
        }

    config = get_openai_config()

    # Si OpenAI no está listo, usamos fallback conservador.
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

    # --------------------------------------------------------
    # Contexto técnico industrial desde libros
    # --------------------------------------------------------
    # Los libros se usan SOLO como apoyo técnico para interpretar
    # mejor la necesidad del cliente.
    #
    # No reemplazan catálogo.
    # No recomiendan productos.
    # No confirman precio, stock ni disponibilidad.
    # --------------------------------------------------------
    industrial_context = build_safe_industrial_context_for_openai(raw_message)

    if industrial_context.get("context"):
        safe_context += (
            "\n\n"
            "CONTEXTO TÉCNICO INDUSTRIAL DE APOYO:\n"
            "Usa los siguientes fragmentos únicamente para entender mejor "
            "la necesidad técnica del cliente y formular una mejor normalized_query, "
            "required_action, required_target, application_context y technical_signals.\n"
            "No recomiendes productos desde estos libros. "
            "No inventes códigos, referencias, marcas, precios, stock ni disponibilidad. "
            "El catálogo real de VIA sigue siendo la única fuente para productos.\n\n"
            f"{industrial_context.get('context')}"
        )

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

    decision_reason = _safe_str(
        parsed.get("decision_reason"),
        _safe_str(parsed.get("reason"), "openai_semantic_interpretation"),
    )

    result = {
        "ok": True,
        "source": "openai",
        "version": AI_INTENT_INTERPRETER_VERSION,
        "used_openai": True,
        "intent_candidate": intent,
        "confidence": confidence,
        "normalized_query": normalized_query,
        "need_type": _safe_str(parsed.get("need_type"), "general"),

        # Necesidad funcional interpretada.
        # Estos campos NO son producto recomendado.
        # Solo describen qué quiere lograr el cliente.
        "required_action": _safe_str(parsed.get("required_action")),
        "required_target": _safe_str(parsed.get("required_target")),
        "application_context": _safe_str(parsed.get("application_context")),

        "detected_code": _safe_str(parsed.get("detected_code")),
        "detected_reference": _safe_str(parsed.get("detected_reference")),

        # Compatibilidad temporal:
        # Estas claves quedan presentes para no romper consumidores antiguos,
        # pero ya no se solicitan ni se usan para decisión.
        "semantic_profile": "",
        "family_hint": "",
        "subtype_hint": "",
        "catalog_line_hints": {},
        "description_short_terms": [],
        "description_long_terms": [],
        "positive_terms": [],
        "negative_terms": [],

        # Contrato runtime.
        "product_need_terms": _clean_list(parsed.get("product_need_terms")),
        "technical_signals": _clean_list(parsed.get("technical_signals")),
        "commercial_signals": _clean_list(parsed.get("commercial_signals")),
        "needs_catalog_search": bool(parsed.get("needs_catalog_search")),
        "should_ask": bool(parsed.get("should_ask")),
        "suggested_question": _safe_str(parsed.get("suggested_question")),
        "decision_reason": decision_reason,

        # Alias legacy para no romper trazas anteriores.
        "reason": decision_reason,

        "model": ai_result.get("model"),
        "response_id": ai_result.get("response_id"),
        "usage": ai_result.get("usage", {}),
        "industrial_context": {
            "used": bool(industrial_context.get("context")),
            "result_count": industrial_context.get("result_count", 0),
            "reason": industrial_context.get("reason"),
        },
    }

    # Regla de seguridad: si dice buscar pero no hay query, no buscamos.
    if result["needs_catalog_search"] and not result["normalized_query"]:
        result["needs_catalog_search"] = False
        result["should_ask"] = True
        result["suggested_question"] = "¿Me confirmas qué producto o aplicación necesitas?"
        result["decision_reason"] = "missing_normalized_query_after_openai"
        result["reason"] = result["decision_reason"]

    return result