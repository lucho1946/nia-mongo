# ============================================================
# knowledge/dynamic_question_engine.py
# ============================================================
# RESPONSABILIDAD:
# Motor dinámico de preguntas técnicas de NIA.
#
# Este módulo usa:
# - contexto conversacional acumulado
# - señales técnicas extraídas del mensaje
# - reglas comerciales del Documento Maestro
#
# Objetivo:
# Reducir preguntas genéricas y preguntar solo lo útil antes
# de buscar o recomendar.
#
# IMPORTANTE:
# Este módulo NO hace retrieval.
# Este módulo NO responde recomendaciones.
# Este módulo NO busca productos.
# Este módulo SOLO decide si conviene preguntar algo más.
#
# CAMBIO CLAVE DE CONTEXTO ACTIVO:
# - Si el usuario solo dice "necesito un producto", NIA NO debe
#   preguntar marca primero.
# - Primero debe preguntar qué producto busca o para qué aplicación.
# - Si el usuario ya respondió un subtipo fuerte, por ejemplo
#   "sensor fotoeléctrico", el sistema puede buscar sin repetir
#   "¿Qué tipo específico necesitas?"
#
# Enfoque alineado con Don Andrés:
# - máximo 3 preguntas técnicas
# - catálogo real
# - no inventar
# - no preguntar por preguntar
# - mantener hilo conversacional
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ============================================================
# CONFIGURACIÓN
# ============================================================

MAX_TECHNICAL_QUESTIONS = 3


# ============================================================
# BANCO GENERAL DE PREGUNTAS
# ============================================================
# Cada pregunta está asociada a un "field" o slot.
#
# El orquestador debe guardar:
# - last_assistant_question_field
# - last_assistant_question_text
# - slot_pendiente
#
# Así, cuando el usuario responda, conversation_memory.py puede
# interpretar esa respuesta según la última pregunta.

QUESTION_BANK: Dict[str, str] = {
    # Pregunta inicial para solicitudes muy genéricas.
    "producto_o_aplicacion": "Claro. ¿Qué producto buscas o para qué aplicación lo necesitas?",

    # Preguntas técnicas/comerciales.
    "subtipo": "¿Qué tipo específico necesitas? Por ejemplo: fotoeléctrico, inductivo, capacitivo, presión o temperatura.",
    "rango": "¿Qué rango de operación o medición necesitas?",
    "salida": "¿Qué salida requiere? Ej: 4-20 mA, 0-10V, PNP o NPN.",
    "conexion": "¿Qué conexión, rosca o montaje necesitas?",
    "voltaje": "¿Qué voltaje necesita?",
    "potencia": "¿Qué potencia o capacidad necesitas?",
    "rpm": "¿Qué velocidad o RPM necesitas?",
    "marca": "¿Tienes alguna marca de preferencia?",
    "referencia": "¿Tienes alguna referencia o código del producto?",
    "aplicacion": "¿Para qué aplicación necesitas el producto?",
    "diametro": "¿Qué diámetro o medida necesitas?",
    "medida": "¿Qué medida, tamaño o capacidad necesitas?",
    "corriente": "¿Qué corriente nominal necesitas?",
    "comunicacion": "¿Necesitas Ethernet, Modbus, RS485 u otra comunicación?",
    "precision": "¿Qué nivel de precisión necesitas?",
    "resolucion": "¿Qué resolución necesitas?",
    "autonomia": "¿Qué autonomía requieres?",
    "fase": "¿Debe ser monofásico o trifásico?",
    "tipo_accion": "¿Debe ser neumático, eléctrico o manual?",
    "material": "¿Requieres algún material específico?",
}


# ============================================================
# PRIORIDAD GENERAL
# ============================================================
# IMPORTANTE:
# Antes el flujo podía preguntar "marca" demasiado pronto.
#
# Ahora, para contexto genérico sin identidad de producto,
# decide_next_step() intercepta primero con producto_o_aplicacion.
#
# Esta prioridad se usa cuando ya existe algo de identidad o cuando
# el orquestador no envía prioridad específica.

GENERAL_PRIORITY: List[str] = [
    "referencia",
    "aplicacion",
    "marca",
]


# ============================================================
# UTILIDADES
# ============================================================

def _normalize_value(value: Any) -> str:
    """
    Convierte un valor a texto normalizado simple.
    No remueve acentos porque aquí solo necesitamos validar presencia
    y reglas de contexto ya normalizadas por otros módulos.
    """
    if value is None:
        return ""

    return str(value).strip().lower()


def _is_empty(value: Any) -> bool:
    """
    Determina si un valor está vacío para efectos conversacionales.
    """
    return value in [None, "", [], {}]


def _has_context_value(context: Dict[str, Any], field: str) -> bool:
    """
    Verifica si el contexto ya tiene un valor para un campo.
    """
    return not _is_empty(context.get(field))


def _get_context_value(context: Dict[str, Any], *fields: str) -> Optional[Any]:
    """
    Devuelve el primer valor existente entre varios campos posibles.
    """
    for field in fields:
        value = context.get(field)

        if not _is_empty(value):
            return value

    return None


def _get_family(context: Dict[str, Any]) -> str:
    """
    Obtiene la familia principal del contexto.
    """
    family = _get_context_value(
        context,
        "familia",
        "categoria",
    )

    return _normalize_value(family)


def _count_context_signals(context: Dict[str, Any]) -> int:
    """
    Cuenta señales técnicas/comerciales útiles.

    No todos los campos pesan igual, pero este conteo ayuda
    a decidir si ya hay información suficiente para buscar.
    """
    useful_fields = [
        "familia",
        "categoria",
        "marca",
        "subtipo",
        "rango",
        "voltaje",
        "potencia",
        "rpm",
        "medida",
        "referencia",
        "codigo_producto",
        "aplicacion",
        "entradas",
        "salidas",
        "comunicacion",
        "salida",
        "conexion",
        "tipo_accion",
        "diametro",
        "presion",
        "corriente",
        "fase",
        "autonomia",
        "material",
        "precision",
        "resolucion",
    ]

    return sum(
        1 for field in useful_fields
        if _has_context_value(context, field)
    )


def _build_question(field: str) -> Optional[Dict[str, Any]]:
    """
    Construye una pregunta estándar para un campo.
    """
    question = QUESTION_BANK.get(field)

    if not question:
        return None

    return {
        "field": field,
        "question": question,
    }


def _has_product_identity(context: Dict[str, Any]) -> bool:
    """
    Determina si ya hay una identidad mínima de producto.

    Si no existe familia, categoría, subtipo, código, referencia
    ni aplicación, NIA no debe preguntar marca todavía.
    Primero debe preguntar qué producto busca o para qué aplicación.
    """
    identity_fields = [
        "familia",
        "categoria",
        "subtipo",
        "codigo_producto",
        "referencia",
        "aplicacion",
    ]

    return any(
        _has_context_value(context, field)
        for field in identity_fields
    )


def _brand_was_declined(context: Dict[str, Any]) -> bool:
    """
    Detecta si el usuario ya dijo que no tiene marca o no le importa.
    """
    if context.get("marca_descartada") is True:
        return True

    status = _normalize_value(context.get("brand_preference_status"))

    return status in ["no_preference", "unknown", "declined"]


def _reference_was_declined(context: Dict[str, Any]) -> bool:
    """
    Detecta si el usuario ya dijo que no tiene referencia/código.
    """
    if context.get("referencia_descartada") is True:
        return True

    status = _normalize_value(context.get("reference_status"))

    return status in ["unknown", "declined"]


def _application_was_declined(context: Dict[str, Any]) -> bool:
    """
    Detecta si el usuario no conoce o no quiere dar aplicación.
    """
    if context.get("aplicacion_descartada") is True:
        return True

    status = _normalize_value(context.get("application_status"))

    return status in ["unknown", "declined"]


def _field_should_be_skipped(context: Dict[str, Any], field: str) -> bool:
    """
    Decide si un campo ya no debe preguntarse porque el usuario
    lo descartó o ya indicó que no lo conoce.
    """
    if field == "marca":
        return _brand_was_declined(context)

    if field == "referencia":
        return _reference_was_declined(context)

    if field == "aplicacion":
        return _application_was_declined(context)

    return False


# ============================================================
# REGLAS DE SUFICIENCIA COMERCIAL
# ============================================================

def _has_enough_context_for_motor(context: Dict[str, Any]) -> bool:
    """
    Motor / motorreductor.

    Para una primera búsqueda comercial segura, NIA puede buscar con:
    - familia motor
    - potencia
    - voltaje

    RPM es útil, pero no debe bloquear siempre.
    Si además hay marca, mucho mejor.
    """
    has_power = _has_context_value(context, "potencia")
    has_voltage = _has_context_value(context, "voltaje")

    return has_power and has_voltage


def _has_enough_context_for_variador(context: Dict[str, Any]) -> bool:
    """
    Variador.

    Datos mínimos:
    - potencia
    - voltaje

    Marca puede ayudar, pero no debe ser obligatoria.
    """
    has_power = _has_context_value(context, "potencia")
    has_voltage = _has_context_value(context, "voltaje")

    return has_power and has_voltage


def _has_enough_context_for_sensor(context: Dict[str, Any]) -> bool:
    """
    Sensor.

    Reglas:
    - Si es sensor de presión/temperatura/nivel/caudal, normalmente
      se necesita una señal adicional como rango, salida, conexión,
      voltaje o marca.
    - Si el subtipo es de presencia/detección industrial
      como fotoeléctrico, inductivo o capacitivo, el subtipo ya es
      una señal fuerte para intentar buscar en catálogo.
    """
    has_subtype = _has_context_value(context, "subtipo")
    subtype = _normalize_value(context.get("subtipo"))

    # --------------------------------------------------------
    # Sensores de detección/presencia.
    # Si el usuario ya dijo "fotoeléctrico", "inductivo",
    # "capacitivo", etc., no debemos repetir "¿qué tipo específico?".
    # --------------------------------------------------------
    if subtype in [
        "fotoelectrico",
        "inductivo",
        "capacitivo",
        "reflectivo",
        "barrera",
        "difuso",
    ]:
        return True

    has_extra_signal = any(
        _has_context_value(context, field)
        for field in [
            "rango",
            "salida",
            "conexion",
            "voltaje",
            "marca",
            "presion",
            "corriente",
            "temperatura",
            "nivel",
            "caudal",
        ]
    )

    return has_subtype and has_extra_signal


def _has_enough_context_for_plc(context: Dict[str, Any]) -> bool:
    """
    PLC.

    Puede buscar si ya tiene al menos una señal técnica fuerte:
    - entradas
    - salidas
    - comunicación
    - marca
    """
    return any(
        _has_context_value(context, field)
        for field in [
            "entradas",
            "salidas",
            "comunicacion",
            "marca",
        ]
    )


def _has_enough_context_for_torquimetro(context: Dict[str, Any]) -> bool:
    """
    Torquímetro.

    Si ya tiene medida/capacidad, debe buscar.
    No debe preguntar marca antes de intentar validar catálogo.
    """
    subtype = _normalize_value(context.get("subtipo"))

    if subtype == "torquimetro" and _has_context_value(context, "medida"):
        return True

    family = _get_family(context)

    if family == "herramienta" and _has_context_value(context, "medida"):
        return True

    return False


def _has_enough_context_for_valvula(context: Dict[str, Any]) -> bool:
    """
    Válvula.

    Puede buscar si ya tiene tipo de acción y una medida técnica,
    o si tiene diámetro + voltaje/presión.
    """
    has_action = _has_context_value(context, "tipo_accion")
    has_diameter = _has_context_value(context, "diametro")
    has_voltage = _has_context_value(context, "voltaje")
    has_pressure = _has_context_value(context, "presion")

    if has_action and (has_diameter or has_voltage or has_pressure):
        return True

    if has_diameter and (has_voltage or has_pressure):
        return True

    return False


def _has_enough_context_for_ups(context: Dict[str, Any]) -> bool:
    """
    UPS.

    Puede buscar con potencia y voltaje/fase/autonomía.
    """
    has_power = _has_context_value(context, "potencia")

    has_extra_signal = any(
        _has_context_value(context, field)
        for field in [
            "voltaje",
            "fase",
            "autonomia",
            "marca",
        ]
    )

    return has_power and has_extra_signal


def _has_enough_context_for_electrico(context: Dict[str, Any]) -> bool:
    """
    Familia eléctrica general.

    Puede buscar si tiene voltaje o corriente,
    y al menos familia/subtipo/marca.
    """
    has_voltage_or_current = (
        _has_context_value(context, "voltaje")
        or _has_context_value(context, "corriente")
    )

    has_identity = any(
        _has_context_value(context, field)
        for field in [
            "familia",
            "categoria",
            "subtipo",
            "marca",
            "referencia",
        ]
    )

    return has_voltage_or_current and has_identity


def _has_enough_context_for_medicion(context: Dict[str, Any]) -> bool:
    """
    Instrumentos de medición.

    Puede buscar si hay familia medición y una señal como rango,
    precisión, subtipo, marca o aplicación.
    """
    return any(
        _has_context_value(context, field)
        for field in [
            "subtipo",
            "rango",
            "precision",
            "resolucion",
            "marca",
            "aplicacion",
        ]
    )


def _context_is_commercially_enough(context: Dict[str, Any]) -> bool:
    """
    Decide si ya existe contexto suficiente para buscar.

    Esta función es clave para que NIA no pregunte por preguntar.

    Importante:
    - No recomienda productos.
    - No valida catálogo.
    - Solo evita preguntas innecesarias cuando ya hay señales suficientes.
    """
    family = _get_family(context)
    signals = _count_context_signals(context)

    if _has_context_value(context, "codigo_producto"):
        return True

    if _has_context_value(context, "referencia"):
        return True

    if family in ["motor", "motorreductor"]:
        return _has_enough_context_for_motor(context)

    if family == "variador":
        return _has_enough_context_for_variador(context)

    if family == "sensor":
        return _has_enough_context_for_sensor(context)

    if family == "plc":
        return _has_enough_context_for_plc(context)

    if family == "herramienta":
        return _has_enough_context_for_torquimetro(context)

    if family == "valvula":
        return _has_enough_context_for_valvula(context)

    if family == "ups":
        return _has_enough_context_for_ups(context)

    if family == "electrico":
        return _has_enough_context_for_electrico(context)

    if family == "medicion":
        return _has_enough_context_for_medicion(context)

    # Regla general:
    # Si ya hay familia/categoría y al menos 3 señales útiles,
    # se busca en vez de seguir preguntando.
    if family and signals >= 3:
        return True

    # Si hay marca + subtipo o marca + aplicación, también puede buscar.
    if (
        _has_context_value(context, "marca")
        and (
            _has_context_value(context, "subtipo")
            or _has_context_value(context, "aplicacion")
        )
    ):
        return True

    return False


# ============================================================
# PREGUNTAS DESDE CONTEXTO
# ============================================================

def get_next_question_from_context(
    context: Dict[str, Any],
    priority_fields: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Devuelve la siguiente pregunta según contexto y prioridad.

    Nota:
    Esta función solo busca el siguiente campo faltante.
    La decisión de si ya se puede buscar se toma en decide_next_step().
    """
    priority = priority_fields or GENERAL_PRIORITY

    for field in priority:
        if _field_should_be_skipped(context, field):
            continue

        if not _has_context_value(context, field):
            question = _build_question(field)

            if question:
                return question

    return None


# ============================================================
# DECISIÓN PRINCIPAL
# ============================================================

def decide_next_step(
    context: Dict[str, Any],
    questions_asked: int = 0,
    priority_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Decide si NIA debe preguntar o buscar.

    Reglas:
    1. Si ya llegó al máximo de preguntas técnicas, debe buscar.
    2. Si el usuario solo dio una intención muy genérica,
       debe preguntar producto/aplicación antes que marca.
    3. Si ya hay contexto comercial suficiente, debe buscar.
    4. Si falta un dato realmente útil, pregunta.
    5. Si no hay pregunta útil, busca.
    """

    if questions_asked >= MAX_TECHNICAL_QUESTIONS:
        return {
            "action": "search",
            "reason": "max_questions_reached",
            "context": context,
        }

    # --------------------------------------------------------
    # Caso genérico:
    # Usuario: "necesito un producto"
    #
    # Si no hay identidad mínima de producto, no preguntamos marca.
    # Primero preguntamos qué producto busca o para qué aplicación.
    # --------------------------------------------------------
    if not _has_product_identity(context):
        return {
            "action": "ask",
            "question": {
                "field": "producto_o_aplicacion",
                "question": QUESTION_BANK["producto_o_aplicacion"],
            },
            "reason": "missing_product_identity",
            "context": context,
        }

    if _context_is_commercially_enough(context):
        return {
            "action": "search",
            "reason": "commercial_context_enough",
            "context": context,
        }

    next_q = get_next_question_from_context(
        context=context,
        priority_fields=priority_fields,
    )

    if next_q:
        return {
            "action": "ask",
            "question": next_q,
            "reason": "missing_relevant_field",
            "context": context,
        }

    return {
        "action": "search",
        "reason": "context_enough",
        "context": context,
    }


# ============================================================
# DECISIÓN USANDO KNOWLEDGE DEL CATÁLOGO
# ============================================================

def decide_with_catalog_knowledge(
    context: Dict[str, Any],
    catalog_knowledge: Optional[Dict[str, Any]] = None,
    questions_asked: int = 0,
) -> Dict[str, Any]:
    """
    Decide siguiente paso usando conocimiento del catálogo.

    catalog_knowledge esperado:
    {
        "categoria": "...",
        "signal_attributes": {...},
        ...
    }

    Por ahora usamos principalmente:
    - campos prioritarios si vienen preparados
    - señales técnicas detectadas
    """

    if questions_asked >= MAX_TECHNICAL_QUESTIONS:
        return {
            "action": "search",
            "reason": "max_questions_reached",
            "context": context,
        }

    # Mismo guardrail para solicitudes demasiado genéricas.
    if not _has_product_identity(context):
        return {
            "action": "ask",
            "question": {
                "field": "producto_o_aplicacion",
                "question": QUESTION_BANK["producto_o_aplicacion"],
            },
            "reason": "missing_product_identity",
            "context": context,
        }

    if _context_is_commercially_enough(context):
        return {
            "action": "search",
            "reason": "commercial_context_enough",
            "context": context,
        }

    if catalog_knowledge is None:
        return decide_next_step(
            context=context,
            questions_asked=questions_asked,
            priority_fields=GENERAL_PRIORITY,
        )

    priority_fields = catalog_knowledge.get("priority_fields")

    if not isinstance(priority_fields, list):
        priority_fields = []

    # Si el knowledge trae señales técnicas, damos prioridad a
    # preguntar por atributos que suelen filtrar mejor.
    signals = catalog_knowledge.get("signal_attributes", {})

    if isinstance(signals, dict):
        signal_keys = list(signals.keys())
        priority_fields = signal_keys + priority_fields

    # Quitamos duplicados manteniendo orden.
    cleaned_priority: List[str] = []

    for field in priority_fields:
        if field not in cleaned_priority:
            cleaned_priority.append(field)

    if not cleaned_priority:
        cleaned_priority = GENERAL_PRIORITY

    return decide_next_step(
        context=context,
        questions_asked=questions_asked,
        priority_fields=cleaned_priority,
    )


# ============================================================
# COMPATIBILIDAD CON QUESTION TREE
# ============================================================

def analyze_dynamic_question(
    context: Dict[str, Any],
    questions_asked: int = 0,
    priority_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Alias semántico para usar desde el orquestador.
    """
    return decide_next_step(
        context=context,
        questions_asked=questions_asked,
        priority_fields=priority_fields,
    )


# ============================================================
# DEBUG
# ============================================================

def explain_dynamic_decision(
    context: Dict[str, Any],
    questions_asked: int = 0,
    priority_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Devuelve explicación de la decisión tomada.
    """
    decision = decide_next_step(
        context=context,
        questions_asked=questions_asked,
        priority_fields=priority_fields,
    )

    return {
        "questions_asked": questions_asked,
        "priority_fields": priority_fields or GENERAL_PRIORITY,
        "commercial_context_enough": _context_is_commercially_enough(context),
        "context_signals": _count_context_signals(context),
        "has_product_identity": _has_product_identity(context),
        "context": context,
        "decision": decision,
    }