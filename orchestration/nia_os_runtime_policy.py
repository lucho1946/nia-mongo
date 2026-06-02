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

def _get_nested_dict(value: Any) -> Dict[str, Any]:
    """
    Devuelve un dict seguro.
    """
    return value if isinstance(value, dict) else {}


def _field_has_value(data: Dict[str, Any], field: str) -> bool:
    """
    Determina si un campo existe y tiene valor útil.
    """
    if not isinstance(data, dict):
        return False

    value = data.get(field)

    return value not in [None, "", [], {}]

def _looks_like_data_request(text: Any) -> bool:
    """
    Detecta si el texto parece estar pidiendo o confirmando datos.

    Importante:
    No basta con que aparezca la palabra 'nombre' o 'correo',
    porque frases como 'Ya tengo nombre y correo' NO deben marcarse
    como repetición.
    """
    normalized = "" if text is None else str(text).lower()

    request_signals = [
        "me confirmas",
        "me confirma",
        "puedes confirmar",
        "puede confirmar",
        "confírmame",
        "confirmame",
        "confirmar",
        "me compartes",
        "me comparte",
        "puedes compartirme",
        "compárteme",
        "comparteme",
        "me indicas",
        "me indica",
        "me das",
        "me da",
        "necesito",
        "necesitaría",
        "necesitaria",
        "cuál es",
        "cual es",
    ]

    return any(signal in normalized for signal in request_signals)


def _text_mentions_any(text: Any, terms: list[str]) -> bool:
    """
    Revisa si el texto contiene alguno de los términos dados.
    """
    normalized = "" if text is None else str(text).lower()

    return any(term in normalized for term in terms)

def detect_repeated_existing_data_request(
    response: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Detecta si NIA está pidiendo datos que ya existen en memoria.

    Esta función NO modifica la respuesta.
    Solo audita la regla:
    must_not_repeat_existing_data.

    Corrección importante:
    La detección se hace por frase, no por texto completo.

    Ejemplo seguro:
    "Encontré el código. ¿Me confirmas más detalle del producto?"

    Aunque el texto completo contiene:
    - "código"
    - "me confirmas"

    No debe marcar codigo_producto como repetido porque no aparecen
    en la misma frase.
    """
    if not isinstance(response, dict):
        response = {}

    response_text = str(response.get("response") or "")

    context = _get_nested_dict(response.get("context"))
    commercial_data = _get_nested_dict(response.get("commercial_data"))
    handoff = _get_nested_dict(response.get("commercial_handoff"))

    repeated_fields: list[str] = []

    sentences = _split_text_into_sentences(response_text)

    if not sentences:
        sentences = [response_text]

    for sentence in sentences:
        sentence_text = str(sentence or "").lower()

        # Solo analizamos frases que realmente parecen pedir datos.
        if not _looks_like_data_request(sentence_text):
            continue

        # ----------------------------------------------------
        # Datos comerciales
        # ----------------------------------------------------
        if (
            (
                _field_has_value(commercial_data, "nombre_cliente")
                or _field_has_value(commercial_data, "cliente")
                or _field_has_value(handoff, "cliente")
            )
            and (
                "nombre" in sentence_text
                or "cómo te llamas" in sentence_text
                or "como te llamas" in sentence_text
            )
        ):
            repeated_fields.append("nombre")

        if (
            (
                _field_has_value(commercial_data, "empresa")
                or _field_has_value(handoff, "empresa")
            )
            and "empresa" in sentence_text
        ):
            repeated_fields.append("empresa")

        if (
            (
                _field_has_value(commercial_data, "correo")
                or _field_has_value(handoff, "correo")
            )
            and (
                "correo" in sentence_text
                or "email" in sentence_text
                or "e-mail" in sentence_text
            )
        ):
            repeated_fields.append("correo")

        if (
            (
                _field_has_value(commercial_data, "telefono")
                or _field_has_value(handoff, "telefono")
            )
            and (
                "teléfono" in sentence_text
                or "telefono" in sentence_text
                or "número de contacto" in sentence_text
                or "numero de contacto" in sentence_text
            )
        ):
            repeated_fields.append("telefono")

        if (
            (
                _field_has_value(commercial_data, "documento_fiscal")
                or _field_has_value(commercial_data, "nit")
                or _field_has_value(commercial_data, "rut")
                or _field_has_value(handoff, "documento_fiscal")
                or _field_has_value(handoff, "nit")
                or _field_has_value(handoff, "rut")
            )
            and (
                "documento fiscal" in sentence_text
                or "nit" in sentence_text
                or "rut" in sentence_text
            )
        ):
            repeated_fields.append("documento_fiscal")

        # ----------------------------------------------------
        # Datos técnicos / producto
        # ----------------------------------------------------
        if (
            _field_has_value(context, "codigo_producto")
            and (
                "código" in sentence_text
                or "codigo" in sentence_text
                or "código de producto" in sentence_text
                or "codigo de producto" in sentence_text
            )
        ):
            repeated_fields.append("codigo_producto")

        if (
            _field_has_value(context, "referencia")
            and "referencia" in sentence_text
        ):
            repeated_fields.append("referencia")

        if (
            _field_has_value(context, "marca")
            and "marca" in sentence_text
        ):
            repeated_fields.append("marca")

        if (
            _field_has_value(context, "voltaje")
            and "voltaje" in sentence_text
        ):
            repeated_fields.append("voltaje")

        if (
            _field_has_value(context, "potencia")
            and "potencia" in sentence_text
        ):
            repeated_fields.append("potencia")

        if (
            _field_has_value(context, "medida")
            and (
                "medida" in sentence_text
                or "capacidad" in sentence_text
                or "tamaño" in sentence_text
                or "tamano" in sentence_text
            )
        ):
            repeated_fields.append("medida")

    repeated_fields = list(dict.fromkeys(repeated_fields))

    return {
        "has_repeated_existing_data_request": len(repeated_fields) > 0,
        "repeated_fields": repeated_fields,
    }
    
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
    - must_not_repeat_existing_data.
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

    # --------------------------------------------------------
    # Regla 1: máximo de preguntas por turno
    # --------------------------------------------------------
    if question_count > max_questions:
        flags.append("too_many_questions_in_turn")

    # --------------------------------------------------------
    # Regla 2: incluir siguiente paso
    # --------------------------------------------------------
    must_include_next_step = policy.get("must_include_next_step") is True
    includes_next_step = has_next_step_signal(response_text)

    if must_include_next_step:
        checked_rules.append("must_include_next_step")

        if not includes_next_step:
            flags.append("missing_next_step")

    # --------------------------------------------------------
    # Regla 3: no repetir datos existentes
    # --------------------------------------------------------
    must_not_repeat_existing_data = (
        policy.get("must_not_repeat_existing_data") is True
    )

    repeated_data_check = {
        "has_repeated_existing_data_request": False,
        "repeated_fields": [],
    }

    if must_not_repeat_existing_data:
        checked_rules.append("must_not_repeat_existing_data")

        repeated_data_check = detect_repeated_existing_data_request(response)

        if repeated_data_check.get("has_repeated_existing_data_request") is True:
            flags.append("repeated_existing_data_request")

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
        "must_not_repeat_existing_data": must_not_repeat_existing_data,
        "repeated_existing_data": repeated_data_check,
        "recommendation": "allow" if ok else "review",
    }
    
def _split_text_into_sentences(text: str) -> list[str]:
    """
    Divide texto en frases simples conservando separadores básicos.

    Importante:
    También separa por saltos de línea y por pipes '|', porque las
    respuestas comerciales de NIA suelen venir así:

    Producto | Marca | Código | Precio

    Para continuar, ¿me confirmas...?

    Si no separamos esos bloques, el auditor puede mezclar una mención
    de código con una pregunta posterior y marcar un falso positivo.
    """
    import re

    text = "" if text is None else str(text).strip()

    if not text:
        return []

    # Normalizamos separadores comunes de las respuestas comerciales.
    normalized = text.replace("|", ". ")
    normalized = re.sub(r"\n+", ". ", normalized)

    parts = re.split(r"(?<=[\.\?\!])\s+", normalized)

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

def append_safe_next_step_if_missing(
    response_text: Any,
    *,
    intent: str = "general",
) -> str:
    """
    Agrega un siguiente paso seguro cuando la respuesta no lo tiene.

    Reglas:
    - No inventa productos.
    - No inventa precios.
    - No inventa stock.
    - No promete entrega.
    - Solo guía al usuario hacia una acción clara.

    Esta función se usa únicamente cuando runtime_policy detecta:
    missing_next_step.
    """
    text = "" if response_text is None else str(response_text).strip()

    if not text:
        text = "Puedo ayudarte con tu solicitud."

    intent = "" if intent is None else str(intent).strip().lower()

    if intent in ["codigo_producto", "producto", "consulta_producto_codigo", "consulta_producto_descripcion"]:
        next_step = (
            "Para continuar, cuéntame si quieres validar una referencia, "
            "comparar opciones o avanzar con una cotización."
        )
    elif intent in ["comercial", "pide_precio", "pide_cotizacion"]:
        next_step = (
            "Para continuar, confírmame el producto o referencia que quieres cotizar."
        )
    elif intent in ["saludo"]:
        next_step = (
            "Cuéntame qué producto industrial necesitas."
        )
    else:
        next_step = (
            "Para continuar, cuéntame qué producto, referencia o especificación quieres validar."
        )

    # Evita duplicar si por alguna razón ya existe una señal de siguiente paso.
    if has_next_step_signal(text):
        return text

    return f"{text}\n\n{next_step}".strip()

def remove_repeated_existing_data_request(
    response_text: Any,
    repeated_fields: list[str],
) -> str:
    """
    Elimina preguntas donde NIA vuelve a pedir datos que ya existen.

    Ejemplo:
    Entrada:
    "Gracias. ¿Me confirmas nombre, empresa y correo?"

    Salida:
    "Gracias."

    No inventa datos.
    No modifica productos, precios, stock ni disponibilidad.
    """
    text = "" if response_text is None else str(response_text).strip()

    if not text or not repeated_fields:
        return text

    sentences = _split_text_into_sentences(text)

    if not sentences:
        return text

    repeated_terms_by_field = {
        "nombre": ["nombre", "cómo te llamas", "como te llamas"],
        "empresa": ["empresa"],
        "correo": ["correo", "email", "e-mail"],
        "telefono": ["teléfono", "telefono", "número de contacto", "numero de contacto"],
        "documento_fiscal": ["documento fiscal", "nit", "rut"],
        "codigo_producto": ["código", "codigo", "código de producto", "codigo de producto"],
        "referencia": ["referencia"],
        "marca": ["marca"],
        "voltaje": ["voltaje"],
        "potencia": ["potencia"],
        "medida": ["medida", "capacidad", "tamaño", "tamano"],
    }

    kept: list[str] = []

    for sentence in sentences:
        sentence_lower = sentence.lower()

        sentence_is_repeated_request = False

        if _looks_like_data_request(sentence_lower):
            for field in repeated_fields:
                terms = repeated_terms_by_field.get(field, [field])

                if _text_mentions_any(sentence_lower, terms):
                    sentence_is_repeated_request = True
                    break

        if sentence_is_repeated_request:
            continue

        kept.append(sentence)

    cleaned = " ".join(kept).strip()

    return cleaned or text


def append_safe_next_step_after_repeated_data(
    response_text: Any,
    *,
    repeated_fields: list[str],
) -> str:
    """
    Agrega un siguiente paso seguro después de quitar una pregunta repetida.

    Importante:
    No listamos los campos repetidos en el texto final.
    Ejemplo: evitamos decir "nombre, empresa, correo",
    porque el auditor puede volver a detectar esas palabras como solicitud repetida.

    No inventa información comercial.
    Solo orienta el flujo.
    """
    text = "" if response_text is None else str(response_text).strip()

    if not repeated_fields:
        return text

    next_step = (
        "Ya tengo los datos necesarios. "
        "Puedo dejar la solicitud en proceso para revisión del asesor."
    )

    if not text:
        return next_step

    if has_next_step_signal(text):
        return text

    return f"{text}\n\n{next_step}".strip()

def enforce_response_against_runtime_policy(
    response: Dict[str, Any],
    nia_os_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Aplica corrección segura sobre la respuesta final según NIA OS.

    Reglas activas:
    - Si la respuesta tiene más preguntas que max_questions_per_turn,
      conserva solo la primera pregunta útil.
    - Si la respuesta no deja siguiente paso, agrega un siguiente paso
      genérico y seguro.

    Esta función puede modificar response["response"], pero:
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
        "reasons": [],
        "before_question_count": initial_check.get("question_count", 0),
        "after_question_count": initial_check.get("question_count", 0),
        "before_includes_next_step": initial_check.get("includes_next_step", False),
        "after_includes_next_step": initial_check.get("includes_next_step", False),
    }

    if initial_check.get("ok") is True:
        response.setdefault("nia_os_runtime_enforcement", enforcement)
        return response

    flags = initial_check.get("flags", [])
    policy = build_runtime_policy_from_nia_os(nia_os_context)

    # --------------------------------------------------------
    # 1. Corregir exceso de preguntas
    # --------------------------------------------------------
    if "too_many_questions_in_turn" in flags:
        max_questions = policy.get("max_questions_per_turn", 1)

        response["response"] = limit_response_to_max_questions(
            response.get("response", ""),
            max_questions=max_questions,
        )

        enforcement["applied"] = True
        enforcement["reasons"].append("too_many_questions_in_turn")

    # --------------------------------------------------------
    # 2. Corregir falta de siguiente paso
    # --------------------------------------------------------
    # Re-evaluamos después de limitar preguntas porque esa corrección
    # puede haber cambiado el texto.
    # --------------------------------------------------------
    intermediate_check = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    if "missing_next_step" in intermediate_check.get("flags", []):
        response["response"] = append_safe_next_step_if_missing(
            response.get("response", ""),
            intent=response.get("intent") or nia_os_context.get("nia_os_intent") or "general",
        )

        enforcement["applied"] = True
        enforcement["reasons"].append("missing_next_step")
        
    # --------------------------------------------------------
    # 3. Corregir solicitud repetida de datos existentes
    # --------------------------------------------------------
    repeated_check = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    if "repeated_existing_data_request" in repeated_check.get("flags", []):
        repeated_data = repeated_check.get("repeated_existing_data") or {}
        repeated_fields = repeated_data.get("repeated_fields", [])

        response["response"] = remove_repeated_existing_data_request(
            response.get("response", ""),
            repeated_fields=repeated_fields,
        )

        response["response"] = append_safe_next_step_after_repeated_data(
            response.get("response", ""),
            repeated_fields=repeated_fields,
        )

        enforcement["applied"] = True
        enforcement["reasons"].append("repeated_existing_data_request")
        enforcement["repeated_fields"] = repeated_fields

    final_check = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    enforcement["after_question_count"] = final_check.get("question_count", 0)
    enforcement["after_includes_next_step"] = final_check.get("includes_next_step", False)

    # Compatibilidad con tests/código anterior que espera "reason"
    if enforcement["reasons"]:
        enforcement["reason"] = enforcement["reasons"][0]
    else:
        enforcement["reason"] = None

    response["nia_os_runtime_enforcement"] = enforcement

    return response