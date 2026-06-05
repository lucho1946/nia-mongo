# ============================================================
# services/technical_question_generator.py
# ============================================================
# RESPONSABILIDAD:
# Generar una pregunta técnica dinámica cuando NIA no tiene
# suficiente certeza para recomendar un producto exacto.
#
# Esta capa NO recomienda productos.
# Esta capa NO busca productos en catálogo.
# Esta capa NO decide el flujo comercial.
# Esta capa NO contiene listas de familias, marcas o productos.
# Esta capa NO contiene preguntas hardcodeadas por caso.
#
# Flujo:
# - El orquestador detecta baja certeza.
# - Este servicio usa OpenAI de forma controlada.
# - OpenAI genera UNA pregunta técnica útil.
# - Este servicio valida la pregunta.
# - El orquestador guarda la pregunta en memoria y responde.
#
# Reglas:
# - Máximo una pregunta.
# - No repetir literalmente lo que el cliente ya dijo.
# - No inventar productos, referencias, marcas, precios ni stock.
# - No mencionar productos concretos si no están confirmados.
# - Preguntar el dato técnico que más reduzca ambigüedad.
# - La pregunta debe ser dinámica según la necesidad, libros y candidatos reales.
#
# Arquitectura:
# - NIA OS gobierna reglas.
# - Libros industriales aportan contexto técnico.
# - Catálogo real aporta candidatos, pero OpenAI NO recomienda.
# - Orquestador decide cuándo preguntar y cuándo recomendar.
# ============================================================

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from knowledge.nia_os.runtime_policy_loader import build_openai_runtime_policy_prompt
from retrieval.industrial_knowledge_retriever import build_industrial_context_for_prompt
from services.ai import generate_assisted_response


logger = logging.getLogger(__name__)

TECHNICAL_QUESTION_GENERATOR_VERSION = "technical_question_generator_v2"


# ============================================================
# UTILIDADES BÁSICAS
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte cualquier valor a string seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """
    Convierte valores comunes a booleano seguro.
    """
    if isinstance(value, bool):
        return value

    text = _safe_str(value).lower()

    if not text:
        return default

    if text in {"true", "1", "yes", "y", "si", "sí", "on"}:
        return True

    if text in {"false", "0", "no", "n", "off"}:
        return False

    return default


def _clean_list(value: Any, max_items: int = 5) -> List[str]:
    """
    Normaliza listas de strings.
    """
    if not isinstance(value, list):
        return []

    result: List[str] = []

    for item in value:
        text = _safe_str(item)

        if text:
            result.append(text)

        if len(result) >= max_items:
            break

    return result


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Extrae JSON desde la respuesta del modelo.

    El modelo debe responder JSON puro, pero toleramos texto adicional.
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


def _sanitize_question(question: str) -> str:
    """
    Limpia y valida formato básico de una pregunta.

    Si el modelo devuelve varias preguntas, conservamos solo la primera.
    """
    text = _safe_str(question)

    if not text:
        return ""

    text = re.sub(r"\s+", " ", text).strip()

    # Si el modelo devuelve varias preguntas, dejamos solo la primera.
    question_mark_index = text.find("?")

    if question_mark_index != -1:
        text = text[: question_mark_index + 1].strip()

    if not text.endswith("?"):
        text = f"{text}?"

    return text


# ============================================================
# GUARDRAILS DE SALIDA
# ============================================================

def _contains_product_code(text: str) -> bool:
    """
    Detecta códigos/referencias tipo producto que no queremos en una pregunta
    técnica dinámica.
    """
    raw = _safe_str(text).upper()

    if not raw:
        return False

    # Códigos tipo P258599 o códigos numéricos largos.
    patterns = [
        r"\bP\d{5,}\b",
        r"\b\d{6,}\b",
    ]

    return any(re.search(pattern, raw) for pattern in patterns)


def _contains_commercial_terms(text: str) -> bool:
    """
    Evita que la pregunta técnica mencione precio, stock o disponibilidad.
    """
    raw = _safe_str(text).lower()

    forbidden_fragments = [
        "precio",
        "precios",
        "cotización",
        "cotizacion",
        "descuento",
        "stock",
        "disponibilidad",
        "tiempo de entrega",
        "entrega",
        "garantía",
        "garantia",
        "comprar",
        "compra",
        "$",
        "cop",
        "usd",
    ]

    return any(fragment in raw for fragment in forbidden_fragments)


def _contains_recommendation_language(text: str) -> bool:
    """
    Evita que OpenAI convierta la pregunta en recomendación.
    """
    raw = _safe_str(text).lower()

    forbidden_fragments = [
        "te recomiendo",
        "recomiendo",
        "la mejor opción",
        "la mejor opcion",
        "el producto ideal",
        "producto recomendado",
        "deberías comprar",
        "deberias comprar",
        "puedes comprar",
        "encontré una opción",
        "encontre una opcion",
        "tenemos disponible",
    ]

    return any(fragment in raw for fragment in forbidden_fragments)


def _mentions_candidate_identity(
    question: str,
    candidates: List[Dict[str, Any]],
) -> bool:
    """
    Evita que la pregunta mencione directamente el nombre, código o referencia
    de un candidato específico.

    Los candidatos se pasan solo para detectar ambigüedad, no para recomendar.
    """
    raw_question = _safe_str(question).lower()

    if not raw_question:
        return False

    for candidate in candidates[:3]:
        if not isinstance(candidate, dict):
            continue

        candidate_values = [
            candidate.get("CODIGO"),
            candidate.get("codigo"),
            candidate.get("REFERENCIA"),
            candidate.get("referencia"),
            candidate.get("NOMBRE_PRODUCTO"),
            candidate.get("nombre"),
        ]

        for value in candidate_values:
            text = _safe_str(value).lower()

            if not text:
                continue

            # No bloqueamos palabras demasiado cortas.
            if len(text) < 5:
                continue

            if text in raw_question:
                return True

    return False


def _is_single_question(question: str) -> bool:
    """
    Verifica que la salida sea una sola intervención interrogativa.

    Importante:
    La regla de NIA es máximo 3 preguntas técnicas por proceso,
    no prohibir que una pregunta técnica incluya dos datos relacionados
    cuando ambos ayudan a filtrar el mismo producto.
    """
    text = _safe_str(question).lower()

    if not text:
        return False

    # Si hay más de un cierre de pregunta, ya son varias preguntas.
    if text.count("?") > 1:
        return False

    # Si hay más de una apertura de pregunta, también son varias preguntas.
    if text.count("¿") > 1:
        return False

    # Evita preguntas tipo lista disfrazada.
    # Esto bloquea casos como:
    # "¿Qué rango necesita? 1) presión 2) caudal 3) temperatura"
    list_patterns = [
        r"\b1\)",
        r"\b2\)",
        r"\b3\)",
        r"\bprimero\b",
        r"\bsegundo\b",
        r"\btercero\b",
    ]

    if any(re.search(pattern, text) for pattern in list_patterns):
        return False

    return True


def _validate_generated_question(
    question: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Valida que la pregunta generada sea segura para enviar al cliente.
    """
    sanitized = _sanitize_question(question)

    if not sanitized:
        return {
            "ok": False,
            "question": "",
            "reason": "empty_question",
        }

    if not _is_single_question(sanitized):
        return {
            "ok": False,
            "question": "",
            "reason": "multiple_questions_detected",
        }

    if _contains_product_code(sanitized):
        return {
            "ok": False,
            "question": "",
            "reason": "question_contains_product_code",
        }

    if _contains_commercial_terms(sanitized):
        return {
            "ok": False,
            "question": "",
            "reason": "question_contains_commercial_terms",
        }

    if _contains_recommendation_language(sanitized):
        return {
            "ok": False,
            "question": "",
            "reason": "question_contains_recommendation_language",
        }

    if _mentions_candidate_identity(sanitized, candidates):
        return {
            "ok": False,
            "question": "",
            "reason": "question_mentions_candidate_identity",
        }

    return {
        "ok": True,
        "question": sanitized,
        "reason": "question_valid",
    }


# ============================================================
# CANDIDATOS Y CONTEXTO
# ============================================================

def _summarize_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resume un candidato real del catálogo sin convertirlo en recomendación.

    Se envía a OpenAI solo para que entienda la ambigüedad entre
    necesidad del cliente y resultados encontrados.
    """
    if not isinstance(candidate, dict):
        return {}

    return {
        "codigo": _safe_str(candidate.get("CODIGO") or candidate.get("codigo")),
        "referencia": _safe_str(candidate.get("REFERENCIA") or candidate.get("referencia")),
        "nombre": _safe_str(candidate.get("NOMBRE_PRODUCTO") or candidate.get("nombre")),
        "marca": _safe_str(candidate.get("MARCA_LET") or candidate.get("marca")),
        "nivel_0": _safe_str(candidate.get("NIVEL_0") or candidate.get("nivel_0")),
        "nivel_1": _safe_str(candidate.get("NIVEL_1") or candidate.get("nivel_1")),
        "nivel_2": _safe_str(candidate.get("NIVEL_2") or candidate.get("nivel_2")),
        "nivel_3": _safe_str(candidate.get("NIVEL_3") or candidate.get("nivel_3")),
        "nivel_4": _safe_str(candidate.get("NIVEL_4") or candidate.get("nivel_4")),
        "descripcion_corta": _safe_str(
            candidate.get("DESCRIPCION_CORTA_PRE")
            or candidate.get("descripcion")
            or candidate.get("descripcion_corta")
        )[:400],
        "descripcion_larga": _safe_str(
            candidate.get("DESCRIPCION_LARGA_PRE")
            or candidate.get("descripcion_larga")
        )[:500],
    }


def _build_fallback_question() -> str:
    """
    Fallback mínimo si OpenAI falla o la pregunta generada no pasa validación.

    No está asociado a productos, familias ni casos específicos.
    Pregunta por especificaciones técnicas discriminantes.
    """
    return (
        "¿Qué rango, capacidad o medida principal necesitas cubrir?"
    )

def _build_industrial_query_from_interpretation(
    user_message: str,
    openai_interpretation: Dict[str, Any] | None,
) -> str:
    """
    Construye una consulta para recuperar contexto industrial real.

    No inventa términos. Usa lo que ya interpretó OpenAI y el mensaje original.
    """
    interpretation = openai_interpretation or {}

    parts = [
        interpretation.get("normalized_query"),
        interpretation.get("required_action"),
        interpretation.get("required_target"),
        interpretation.get("application_context"),
        " ".join(_clean_list(interpretation.get("product_need_terms"), max_items=8)),
        " ".join(_clean_list(interpretation.get("technical_signals"), max_items=8)),
        user_message,
    ]

    query = " ".join(_safe_str(part) for part in parts if _safe_str(part))

    return query or _safe_str(user_message)


def _ensure_industrial_context(
    *,
    user_message: str,
    openai_interpretation: Dict[str, Any] | None = None,
    industrial_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Garantiza que el generador tenga contexto industrial real si es posible.

    Si ya viene un contexto con texto, lo respeta.
    Si solo viene metadata o viene vacío, consulta los libros industriales.
    Si falla, devuelve contexto vacío sin romper el flujo.
    """
    provided = industrial_context or {}

    provided_context = _safe_str(provided.get("context"))

    if provided_context:
        return {
            "used": True,
            "result_count": int(provided.get("result_count") or 0),
            "context": provided_context[:2200],
            "reason": provided.get("reason") or "provided_industrial_context",
        }

    try:
        query = _build_industrial_query_from_interpretation(
            user_message=user_message,
            openai_interpretation=openai_interpretation,
        )

        result = build_industrial_context_for_prompt(
            query=query,
            max_results=3,
            max_chars=2200,
        )

        context = _safe_str(result.get("context"))

        return {
            "used": bool(context),
            "result_count": int(result.get("result_count") or 0),
            "context": context[:2200],
            "reason": (
                "industrial_context_rebuilt"
                if context
                else "industrial_context_empty"
            ),
        }

    except Exception as exc:
        logger.warning("No se pudo reconstruir contexto industrial: %s", exc)

        return {
            "used": False,
            "result_count": 0,
            "context": "",
            "reason": f"industrial_context_error: {exc}",
        }


# ============================================================
# CONTEXTO PARA OPENAI
# ============================================================

def build_technical_question_context(
    *,
    user_message: str,
    openai_interpretation: Dict[str, Any] | None = None,
    industrial_context: Dict[str, Any] | None = None,
    top_catalog_candidates: List[Dict[str, Any]] | None = None,
    questions_asked: int = 0,
    previous_questions: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Construye contexto seguro para generar una pregunta técnica dinámica.

    Responsabilidad:
    - Generar instrucciones específicas para que OpenAI proponga UNA pregunta técnica.
    - Usar reglas runtime de NIA OS.
    - Usar libros industriales como contexto técnico.
    - Usar candidatos reales solo como evidencia de ambigüedad.
    - No recomendar productos.
    - No inventar marcas, referencias, precios, stock ni disponibilidad.

    Esta función NO contiene reglas por producto específico.
    No dice:
    - si es pozómetro pregunta profundidad;
    - si es manómetro pregunta presión;
    - si es PLC pregunta modelo.

    En su lugar, orienta al modelo a identificar el dato técnico más discriminante
    según la necesidad, el contexto industrial y los candidatos reales.
    """
    interpretation = openai_interpretation or {}
    candidates = top_catalog_candidates or []
    previous = _clean_list(previous_questions or [], max_items=3)

    industrial = _ensure_industrial_context(
        user_message=user_message,
        openai_interpretation=interpretation,
        industrial_context=industrial_context,
    )

    summarized_candidates = [
        _summarize_candidate(candidate)
        for candidate in candidates[:3]
        if isinstance(candidate, dict)
    ]

    runtime_policy = build_openai_runtime_policy_prompt()

    context_payload = {
        "mensaje_cliente": _safe_str(user_message),
        "interpretacion_semantica": {
            "intent_candidate": interpretation.get("intent_candidate"),
            "normalized_query": interpretation.get("normalized_query"),
            "need_type": interpretation.get("need_type"),
            "required_action": interpretation.get("required_action"),
            "required_target": interpretation.get("required_target"),
            "application_context": interpretation.get("application_context"),
            "product_need_terms": interpretation.get("product_need_terms", []),
            "technical_signals": interpretation.get("technical_signals", []),
            "commercial_signals": interpretation.get("commercial_signals", []),
            "technical_clarification": interpretation.get("technical_clarification"),
            "memory_enriched": interpretation.get("memory_enriched", False),
        },
        "contexto_industrial": {
            "used": industrial.get("used", False),
            "result_count": industrial.get("result_count", 0),
            "context": _safe_str(industrial.get("context"))[:2200],
            "reason": industrial.get("reason"),
        },
        "candidatos_catalogo_reales_resumidos": summarized_candidates,
        "preguntas_tecnicas_hechas": questions_asked,
        "limite_preguntas_tecnicas": 3,
        "preguntas_previas": previous,
    }

    prompt_context = (
        f"{runtime_policy}\n\n"

        "TAREA ACTUAL:\n"
        "NIA está en intención técnica. Todavía no tiene certeza suficiente "
        "para recomendar un producto exacto del catálogo real.\n"
        "Debes generar UNA sola pregunta técnica que ayude a reducir la ambigüedad "
        "y acerque la conversación al producto correcto.\n\n"

        "SEPARACIÓN DE RESPONSABILIDADES:\n"
        "- Tú NO recomiendas productos.\n"
        "- Tú NO seleccionas producto final.\n"
        "- Tú NO confirmas disponibilidad, precio, stock ni tiempo de entrega.\n"
        "- Tú NO inventas referencias, códigos, marcas ni especificaciones.\n"
        "- Tú SOLO propones una pregunta técnica útil para que NIA pueda seguir filtrando.\n\n"

        "CRITERIO PRINCIPAL:\n"
        "La pregunta debe pedir el dato técnico más discriminante para diferenciar "
        "entre productos reales del catálogo.\n"
        "Un dato discriminante es aquel que, al responderse, ayuda a separar productos "
        "parecidos o evita recomendar un producto incompatible.\n\n"

        "TIPOS DE DATOS TÉCNICOS DISCRIMINANTES:\n"
        "Puedes preguntar por un único dato de este tipo cuando el contexto lo justifique:\n"
        "- rango de trabajo;\n"
        "- capacidad;\n"
        "- medida principal;\n"
        "- profundidad;\n"
        "- altura;\n"
        "- alcance;\n"
        "- presión;\n"
        "- caudal;\n"
        "- temperatura;\n"
        "- nivel;\n"
        "- precisión;\n"
        "- resolución;\n"
        "- diámetro;\n"
        "- conexión;\n"
        "- salida o señal;\n"
        "- protocolo de comunicación;\n"
        "- compatibilidad con otro equipo;\n"
        "- dimensión;\n"
        "- material;\n"
        "- tipo de montaje;\n"
        "- condición de operación.\n\n"

        "REGLAS PARA ELEGIR LA PREGUNTA:\n"
        "- Genera solo UNA pregunta.\n"
        "- La pregunta debe pedir UN SOLO dato técnico.\n"
        "- La pregunta debe ser una sola intervención interrogativa.\n"
        "- Puede incluir dos datos técnicos relacionados si ambos son necesarios para filtrar el mismo producto.\n"
        "- No conviertas la pregunta en una lista larga de requisitos.\n"
        "- No hagas varias preguntas separadas.\n"
        "- Si usas una pregunta compuesta, debe ser breve y coherente, por ejemplo: rango y unidad, marca y modelo, tipo y capacidad.\n"
        "- Si el cliente expresa una necesidad de medición, prioriza el rango, capacidad, "
        "medida, profundidad, altura, presión, caudal, temperatura, nivel o precisión, "
        "según lo que el contexto indique como más útil.\n"
        "- Si el cliente expresa una necesidad de comunicación, conexión o integración, "
        "prioriza protocolo, puerto, señal, interfaz o compatibilidad con el equipo existente.\n"
        "- Si el cliente expresa una necesidad de potencia, movimiento o accionamiento, "
        "prioriza capacidad, potencia, voltaje, torque, velocidad, carga o montaje.\n"
        "- Si el cliente expresa una necesidad de detección o sensado, prioriza rango, "
        "tipo de salida, distancia, condición de detección, montaje o ambiente.\n"
        "- No preguntes por fluido, líquido, material o ambiente como primera opción "
        "si el contexto no muestra que ese dato sea el principal diferenciador técnico.\n"
        "- No repitas literalmente todo lo que el cliente ya dijo.\n"
        "- No repitas preguntas previas.\n"
        "- Si los candidatos reales parecen incompatibles con la función solicitada, "
        "pregunta por el dato técnico que más ayude a aclarar la función o especificación.\n\n"

        "USO DE RANGOS, UNIDADES Y EJEMPLOS:\n"
        "- Puedes incluir unidades, rangos o alternativas técnicas SOLO si aparecen en:\n"
        "  1. el mensaje del cliente;\n"
        "  2. el contexto industrial recuperado;\n"
        "  3. los candidatos reales del catálogo;\n"
        "  4. la interpretación semántica recibida.\n"
        "- No inventes rangos como 0 a 100 m, 10 a 20 psi, 4-20 mA, RS485, NPT, "
        "si no aparecen en el contexto disponible.\n"
        "- Si no hay evidencia suficiente para dar ejemplos concretos, pregunta por el dato "
        "sin inventar valores.\n\n"

        "ESTILO DE LA PREGUNTA:\n"
        "- Debe sonar humana, breve, técnica y comercial.\n"
        "- No uses explicación larga.\n"
        "- No digas 'para poder ayudarte mejor' si puedes preguntar directo.\n"
        "- No menciones 'catálogo', 'sistema', 'OpenAI', 'modelo', 'NIA OS' ni reglas internas.\n"
        "- No menciones productos candidatos específicos.\n"
        "- No menciones códigos, referencias, precios, stock ni disponibilidad.\n\n"

        "FORMATO DE SALIDA:\n"
        "Devuelve SOLO JSON válido.\n"
        "No agregues texto antes ni después del JSON.\n\n"
        "{\n"
        '  "should_ask": true,\n'
        '  "question": "pregunta técnica única y breve",\n'
        '  "field": "technical_clarification",\n'
        '  "reason": "por qué esta pregunta ayuda a reducir ambigüedad"\n'
        "}\n\n"

        "CONTEXTO SEGURO PARA GENERAR LA PREGUNTA:\n"
        f"{json.dumps(context_payload, ensure_ascii=False, indent=2)}"
    )

    return {
        "prompt_context": prompt_context,
        "industrial_context": industrial,
        "summarized_candidates": summarized_candidates,
    }


# ============================================================
# API INTERNA
# ============================================================

def generate_dynamic_technical_question(
    *,
    user_message: str,
    openai_interpretation: Dict[str, Any] | None = None,
    industrial_context: Dict[str, Any] | None = None,
    top_catalog_candidates: List[Dict[str, Any]] | None = None,
    questions_asked: int = 0,
    previous_questions: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Genera una pregunta técnica dinámica usando OpenAI.

    El orquestador decide cuándo llamar esta función.
    Esta función solo propone la pregunta.
    """
    candidates = top_catalog_candidates or []

    if questions_asked >= 3:
        return {
            "ok": True,
            "version": TECHNICAL_QUESTION_GENERATOR_VERSION,
            "used_openai": False,
            "should_ask": False,
            "question": "",
            "field": "technical_clarification",
            "reason": "max_technical_questions_reached",
        }

    fallback_question = _build_fallback_question()

    context_result = build_technical_question_context(
        user_message=user_message,
        openai_interpretation=openai_interpretation,
        industrial_context=industrial_context,
        top_catalog_candidates=candidates,
        questions_asked=questions_asked,
        previous_questions=previous_questions,
    )

    safe_context = context_result.get("prompt_context", "")

    fallback_payload = json.dumps(
        {
            "should_ask": True,
            "question": fallback_question,
            "field": "technical_clarification",
            "reason": "fallback_dynamic_question",
        },
        ensure_ascii=False,
    )

    ai_result = generate_assisted_response(
        user_message=user_message,
        safe_context=safe_context,
        task="generar_pregunta_tecnica_dinamica",
        fallback_response=fallback_payload,
    )

    if not ai_result.get("ok"):
        return {
            "ok": False,
            "version": TECHNICAL_QUESTION_GENERATOR_VERSION,
            "used_openai": ai_result.get("used_openai", False),
            "should_ask": True,
            "question": fallback_question,
            "field": "technical_clarification",
            "reason": ai_result.get("reason") or "openai_unavailable_question_fallback",
            "industrial_context": context_result.get("industrial_context", {}),
            "openai_result": {
                "ok": ai_result.get("ok"),
                "reason": ai_result.get("reason"),
            },
        }

    parsed = _extract_json_object(ai_result.get("response", ""))

    if not parsed:
        return {
            "ok": False,
            "version": TECHNICAL_QUESTION_GENERATOR_VERSION,
            "used_openai": True,
            "should_ask": True,
            "question": fallback_question,
            "field": "technical_clarification",
            "reason": "invalid_question_json_fallback",
            "industrial_context": context_result.get("industrial_context", {}),
            "raw_response": _safe_str(ai_result.get("response"))[:500],
        }

    raw_question = _safe_str(parsed.get("question"))
    validation = _validate_generated_question(
        question=raw_question,
        candidates=candidates,
    )

    if validation.get("ok") is True:
        question = validation.get("question", "")
        validation_reason = validation.get("reason")
        rejected_question = ""
    else:
        rejected_question = raw_question
        question = fallback_question
        validation_reason = validation.get("reason")

    should_ask = _safe_bool(parsed.get("should_ask"), default=True)

    if not question:
        question = fallback_question
        should_ask = True

    return {
        "ok": True,
        "version": TECHNICAL_QUESTION_GENERATOR_VERSION,
        "used_openai": True,
        "should_ask": should_ask,
        "question": question,
        "field": "technical_clarification",
        "reason": _safe_str(
            parsed.get("reason"),
            "dynamic_technical_question_generated",
        ),
        "validation": {
            "ok": validation.get("ok", False),
            "reason": validation_reason,
            "rejected_question": rejected_question,
        },
        "industrial_context": context_result.get("industrial_context", {}),
        "candidate_count": len(candidates),
        "model": ai_result.get("model"),
        "response_id": ai_result.get("response_id"),
        "usage": ai_result.get("usage", {}),
    }