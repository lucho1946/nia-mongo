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


def evaluate_response_against_runtime_policy(
    response: Dict[str, Any],
    nia_os_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evalúa una respuesta final contra la política runtime de NIA OS.

    Esta función NO modifica la respuesta.
    Solo genera diagnóstico para trazabilidad interna.

    Primera validación:
    - max_questions_per_turn.

    Próximas validaciones:
    - siguiente paso comercial;
    - uso de memoria antes de preguntar;
    - no repetición de datos;
    - no inventar información comercial.
    """
    if not isinstance(response, dict):
        response = {}

    policy = build_runtime_policy_from_nia_os(nia_os_context)

    response_text = response.get("response", "")
    question_count = count_questions_in_text(response_text)
    max_questions = policy.get("max_questions_per_turn", 1)

    flags = []

    if question_count > max_questions:
        flags.append("too_many_questions_in_turn")

    ok = len(flags) == 0

    return {
        "ok": ok,
        "source": "nia_os_runtime_policy",
        "checked_rules": [
            "max_questions_per_turn",
        ],
        "flags": flags,
        "question_count": question_count,
        "max_questions_per_turn": max_questions,
        "recommendation": "allow" if ok else "review",
    }