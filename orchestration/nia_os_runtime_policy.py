# ============================================================
# orchestration/nia_os_runtime_policy.py
# ============================================================
# RESPONSABILIDAD:
# Convertir el contexto NIA OS cargado desde JSON en reglas runtime
# simples y seguras para el orquestador.
#
# Este módulo NO:
# - responde al usuario;
# - busca productos;
# - modifica MongoDB;
# - reemplaza el orquestador;
# - expone módulos internos al cliente.
#
# Objetivo:
# Empezar a usar NIA OS como fuente de reglas operativas reales,
# no solo como metadata.
#
# Primera integración:
# - response_policy.max_questions_per_turn
# - response_policy.must_use_memory_before_asking
# - response_policy.must_include_next_step
# - response_policy.must_not_repeat_existing_data
# - response_policy.must_not_invent_commercial_information
# ============================================================

from __future__ import annotations

from typing import Any, Dict


DEFAULT_RUNTIME_POLICY = {
    "max_questions_per_turn": 1,
    "must_use_memory_before_asking": True,
    "must_include_next_step": True,
    "must_not_repeat_existing_data": True,
    "must_not_invent_commercial_information": True,
}


def _as_bool(value: Any, default: bool) -> bool:
    """
    Convierte valores comunes a booleano seguro.
    """
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = str(value).strip().lower()

    if text in ["1", "true", "yes", "si", "sí", "on"]:
        return True

    if text in ["0", "false", "no", "off"]:
        return False

    return default


def _as_int(value: Any, default: int, *, min_value: int = 1, max_value: int = 5) -> int:
    """
    Convierte un valor a entero seguro con límites.
    """
    try:
        number = int(value)
    except Exception:
        number = default

    if number < min_value:
        number = min_value

    if number > max_value:
        number = max_value

    return number


def build_runtime_policy_from_nia_os(
    nia_os_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Construye política runtime desde nia_os_context.

    Espera:
    nia_os_context["commercial_spine"]["response_policy"]

    Si algo falta, usa defaults seguros.
    """
    if not isinstance(nia_os_context, dict):
        nia_os_context = {}

    commercial_spine = nia_os_context.get("commercial_spine") or {}

    if not isinstance(commercial_spine, dict):
        commercial_spine = {}

    response_policy = commercial_spine.get("response_policy") or {}

    if not isinstance(response_policy, dict):
        response_policy = {}

    return {
        "max_questions_per_turn": _as_int(
            response_policy.get("max_questions_per_turn"),
            DEFAULT_RUNTIME_POLICY["max_questions_per_turn"],
            min_value=1,
            max_value=5,
        ),
        "must_use_memory_before_asking": _as_bool(
            response_policy.get("must_use_memory_before_asking"),
            DEFAULT_RUNTIME_POLICY["must_use_memory_before_asking"],
        ),
        "must_include_next_step": _as_bool(
            response_policy.get("must_include_next_step"),
            DEFAULT_RUNTIME_POLICY["must_include_next_step"],
        ),
        "must_not_repeat_existing_data": _as_bool(
            response_policy.get("must_not_repeat_existing_data"),
            DEFAULT_RUNTIME_POLICY["must_not_repeat_existing_data"],
        ),
        "must_not_invent_commercial_information": _as_bool(
            response_policy.get("must_not_invent_commercial_information"),
            DEFAULT_RUNTIME_POLICY["must_not_invent_commercial_information"],
        ),
        "source": "nia_os_commercial_spine.response_policy",
    }


def get_max_questions_per_turn(nia_os_context: Dict[str, Any]) -> int:
    """
    Devuelve máximo de preguntas por turno definido por NIA OS.

    En el commercial_spine actual debe ser 1.
    """
    policy = build_runtime_policy_from_nia_os(nia_os_context)
    return policy["max_questions_per_turn"]


def should_ask_question_this_turn(
    *,
    questions_to_ask_now: int,
    nia_os_context: Dict[str, Any],
) -> bool:
    """
    Decide si NIA puede hacer otra pregunta en este turno.

    Ejemplo:
    - max_questions_per_turn = 1
    - si ya va 1 pregunta, no debe agregar otra.
    """
    max_questions = get_max_questions_per_turn(nia_os_context)

    try:
        current = int(questions_to_ask_now)
    except Exception:
        current = 0

    return current < max_questions

def count_questions_in_text(text: Any) -> int:
    """
    Cuenta preguntas explícitas en un texto.

    Primera versión simple:
    - cuenta signos de interrogación de cierre;
    - si no hay signo, intenta detectar frases interrogativas comunes.

    Esto no reemplaza NLP avanzado, pero es suficiente para auditar
    la regla de NIA OS: máximo una pregunta por turno.
    """
    text = "" if text is None else str(text).strip()

    if not text:
        return 0

    explicit_questions = text.count("?") + text.count("¿")

    # En español normalmente una pregunta puede traer ¿ y ?.
    # Para no contar doble, usamos el mayor entre ambos pares.
    if explicit_questions > 0:
        return max(text.count("?"), text.count("¿"), 1)

    normalized = text.lower()

    question_starters = [
        "qué ",
        "que ",
        "cuál ",
        "cual ",
        "cuánto ",
        "cuanto ",
        "cuánta ",
        "cuanta ",
        "confirmas ",
        "me confirmas ",
        "puedes confirmar ",
        "necesitas ",
        "quieres ",
    ]

    if any(starter in normalized for starter in question_starters):
        return 1

    return 0


def has_next_step_signal(text: Any) -> bool:
    """
    Detecta si una respuesta deja un siguiente paso claro.

    No inventa ni modifica respuesta.
    Solo audita señales textuales comunes de avance comercial.

    Ejemplos válidos:
    - Para continuar...
    - El siguiente paso...
    - ¿Me confirmas...?
    - Puedo dejar la cotización...
    - Puedes compartirme...
    - ¿Quieres avanzar...?
    """
    text = "" if text is None else str(text).strip()

    if not text:
        return False

    normalized = text.lower()

    next_step_signals = [
        "para continuar",
        "siguiente paso",
        "próximo paso",
        "proximo paso",
        "puedo dejar",
        "puedo ayudarte",
        "para ayudarte",
        "me confirmas",
        "puedes confirmar",
        "puedes compartirme",
        "quieres avanzar",
        "quieres que",
        "si quieres",
        "si deseas",
        "déjame",
        "dejame",
        "compárteme",
        "comparteme",
        "confirmame",
        "confírmame",
        "validar",
        "cotización",
        "cotizacion",
        "proforma",
        "asesor",
        "revisar equivalentes",
        "afinar la búsqueda",
        "afinar la busqueda",
        "qué producto",
        "que producto",
        "producto industrial necesitas",
        "producto necesitas",
        "qué necesitas",
        "que necesitas",
    ]

    return any(signal in normalized for signal in next_step_signals)


def evaluate_response_against_runtime_policy(
    response: Dict[str, Any],
    nia_os_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evalúa una respuesta final contra la política runtime de NIA OS.

    Esta función NO modifica la respuesta.
    Solo genera diagnóstico para trazabilidad interna.

    Reglas auditadas:
    - max_questions_per_turn.
    - must_include_next_step.
    """
    if not isinstance(response, dict):
        response = {}

    policy = build_runtime_policy_from_nia_os(nia_os_context)

    response_text = response.get("response", "")
    question_count = count_questions_in_text(response_text)
    max_questions = policy.get("max_questions_per_turn", 1)

    checked_rules = [
        "max_questions_per_turn",
    ]

    flags = []

    if question_count > max_questions:
        flags.append("too_many_questions_in_turn")

    must_include_next_step = policy.get("must_include_next_step") is True
    includes_next_step = has_next_step_signal(response_text)

    if must_include_next_step:
        checked_rules.append("must_include_next_step")

        if not includes_next_step:
            flags.append("missing_next_step")

    ok = len(flags) == 0

    return {
        "ok": ok,
        "source": "nia_os_runtime_policy",
        "checked_rules": checked_rules,
        "flags": flags,
        "question_count": question_count,
        "max_questions_per_turn": max_questions,
        "must_include_next_step": must_include_next_step,
        "includes_next_step": includes_next_step,
        "recommendation": "allow" if ok else "review",
    }
    
def _split_text_into_sentences(text: str) -> list[str]:
    """
    Divide texto en frases simples conservando separadores básicos.

    No busca perfección lingüística; solo necesitamos una separación
    segura para detectar y conservar la primera pregunta.
    """
    import re

    text = "" if text is None else str(text).strip()

    if not text:
        return []

    parts = re.split(r"(?<=[\.\?\!])\s+", text)

    return [
        part.strip()
        for part in parts
        if part and part.strip()
    ]


def _is_question_sentence(sentence: str) -> bool:
    """
    Determina si una frase parece pregunta.
    """
    sentence = "" if sentence is None else str(sentence).strip()

    if not sentence:
        return False

    if "?" in sentence or "¿" in sentence:
        return True

    normalized = sentence.lower()

    starters = [
        # --- Tu lista base original ---
        "qué ",
        "que ",
        "cuál ",
        "cual ",
        "cuánto ",
        "cuanto ",
        "cuánta ",
        "cuanta ",
        "me confirmas ",
        "puedes confirmar ",
        "quieres ",
        "necesitas ",

        # --- Variantes en plural ---
        "cuáles ",
        "cuales ",
        "cuántos ",
        "cuantos ",
        "cuántas ",
        "cuantas ",

        # --- Pronombres de persona (singular y plural) ---
        "quién ",
        "quien ",
        "quiénes ",
        "quienes ",

        # --- Adverbios interrogativos fundamentales de lugar, tiempo y modo ---
        "cómo ",
        "como ",
        "dónde ",
        "donde ",
        "cuándo ",
        "cuando ",
        "adónde ",
        "adonde ",

        # --- Pronombres interrogativos precedidos por preposiciones comunes ---
        "por qué ",
        "por que ",
        "para qué ",
        "para que ",
        "a qué ",
        "de qué ",
        "en qué ",
        "con qué ",
        "a quién ",
        "con quién ",
        "de quién ",
        "a quiénes ",
        "con quiénes ",
        "de quiénes ",
        "a dónde ",
        "de dónde ",
        "en dónde ",
        "por dónde ",
        "hacia dónde ",
        "desde cuándo ",
        "hasta cuándo ",
        "a cuál ",
        "de cuál ",
        "en cuál ",
        "con cuál ",
        "a cuáles ",
        "de cuáles ",
        "en cuáles ",
        "con cuáles ",
        "a cuánto ",
        "de cuánto ",
        "en cuánto ",
    ]

    return any(normalized.startswith(starter) for starter in starters)


def limit_response_to_max_questions(
    response_text: Any,
    *,
    max_questions: int = 1,
) -> str:
    """
    Reduce una respuesta para que no supere el máximo de preguntas.

    Estrategia segura:
    - conserva todo texto afirmativo previo;
    - conserva solo las primeras N preguntas;
    - elimina preguntas adicionales;
    - no agrega información comercial nueva.

    Ejemplo:
    Entrada:
    "¿Qué producto necesitas? ¿Qué marca prefieres? ¿Qué rango buscas?"

    Salida:
    "¿Qué producto necesitas?"
    """
    text = "" if response_text is None else str(response_text).strip()

    if not text:
        return ""

    try:
        max_questions = int(max_questions)
    except Exception:
        max_questions = 1

    if max_questions < 1:
        max_questions = 1

    sentences = _split_text_into_sentences(text)

    if not sentences:
        return text

    kept: list[str] = []
    question_count = 0

    for sentence in sentences:
        if _is_question_sentence(sentence):
            if question_count >= max_questions:
                continue

            question_count += 1
            kept.append(sentence)
            continue

        kept.append(sentence)

    cleaned = " ".join(kept).strip()

    return cleaned or text


def enforce_response_against_runtime_policy(
    response: Dict[str, Any],
    nia_os_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Aplica corrección segura sobre la respuesta final según NIA OS.

    Primera regla activa:
    - Si la respuesta tiene más preguntas que max_questions_per_turn,
      conserva solo la primera pregunta útil.

    Esta función sí puede modificar response["response"], pero:
    - no cambia productos;
    - no cambia cards;
    - no cambia precios;
    - no cambia disponibilidad;
    - no inventa datos;
    - deja metadata de corrección.
    """
    if not isinstance(response, dict):
        response = {
            "intent": "general",
            "response": "",
        }

    initial_check = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    enforcement = {
        "applied": False,
        "source": "nia_os_runtime_policy",
        "reason": None,
        "before_question_count": initial_check.get("question_count", 0),
        "after_question_count": initial_check.get("question_count", 0),
    }

    if initial_check.get("ok") is True:
        response.setdefault("nia_os_runtime_enforcement", enforcement)
        return response

    flags = initial_check.get("flags", [])

    if "too_many_questions_in_turn" not in flags:
        response.setdefault("nia_os_runtime_enforcement", enforcement)
        return response

    policy = build_runtime_policy_from_nia_os(nia_os_context)
    max_questions = policy.get("max_questions_per_turn", 1)

    original_text = response.get("response", "")

    cleaned_text = limit_response_to_max_questions(
        original_text,
        max_questions=max_questions,
    )

    response["response"] = cleaned_text

    final_check = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    enforcement = {
        "applied": True,
        "source": "nia_os_runtime_policy",
        "reason": "too_many_questions_in_turn",
        "before_question_count": initial_check.get("question_count", 0),
        "after_question_count": final_check.get("question_count", 0),
    }

    response["nia_os_runtime_enforcement"] = enforcement

    return response