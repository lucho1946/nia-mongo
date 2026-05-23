# ============================================================
# knowledge/question_tree.py
# ============================================================
# RESPONSABILIDAD:
# Motor conversacional técnico de NIA.
#
# Este módulo decide:
# - cuándo preguntar
# - qué preguntar
# - cuándo ya existe suficiente contexto
# - cuándo se debe ejecutar retrieval
#
# Alineado con el documento maestro:
# - máximo 3 preguntas técnicas
# - preguntas relevantes según categoría
# - contexto acumulado
# - catálogo industrial real
# - flujo comercial técnico
#
# IMPORTANTE:
# Este módulo NO hace retrieval.
# Este módulo NO responde directamente.
# Este módulo SOLO toma decisiones conversacionales.
#
# ============================================================

from __future__ import annotations

import re

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

# ============================================================
# CONFIGURACIÓN GLOBAL
# ============================================================

MAX_QUESTIONS = 3


# ============================================================
# CATEGORÍAS BASE
# ============================================================
# IMPORTANTE:
# Esto NO pretende modelar TODO el catálogo VIA.
#
# Solo sirve como:
# - guía conversacional
# - agrupación semántica
# - ayuda para preguntas relevantes
#
# El catálogo real sigue siendo Mongo.
# ============================================================

CATEGORY_KEYWORDS: Dict[str, List[str]] = {

    # --------------------------------------------------------
    # Sensores / instrumentación
    # --------------------------------------------------------
    "sensor": [
        "sensor",
        "sensores",
        "transmisor",
        "transmisores",
        "presion",
        "presión",
        "temperatura",
        "nivel",
        "caudal",
        "detector",
        "encoder",
        "final de carrera",
    ],

    # --------------------------------------------------------
    # Motores / movimiento
    # --------------------------------------------------------
    "motor": [
        "motor",
        "motores",
        "servomotor",
        "motorreductor",
        "reductor",
    ],

    # --------------------------------------------------------
    # Variadores / drives
    # --------------------------------------------------------
    "variador": [
        "variador",
        "drive",
        "vfd",
        "arrancador",
    ],

    # --------------------------------------------------------
    # PLC / automatización
    # --------------------------------------------------------
    "plc": [
        "plc",
        "controlador",
        "hmi",
        "pantalla",
        "touch",
        "modulo",
        "módulo",
        "io",
        "entradas",
        "salidas",
    ],

    # --------------------------------------------------------
    # Eléctrico
    # --------------------------------------------------------
    "electrico": [
        "breaker",
        "contactor",
        "rele",
        "relé",
        "guardamotor",
        "disyuntor",
        "interruptor",
        "fuente",
        "switching",
        "ups",
    ],

    # --------------------------------------------------------
    # Válvulas / neumática
    # --------------------------------------------------------
    "valvula": [
        "valvula",
        "válvula",
        "electrovalvula",
        "electroválvula",
        "cilindro",
        "neumatica",
        "neumática",
        "filtro",
        "regulador",
        "lubricador",
    ],

    # --------------------------------------------------------
    # Herramienta industrial
    # --------------------------------------------------------
    "herramienta": [
        "herramienta",
        "torquimetro",
        "torquímetro",
        "taladro",
        "esmeril",
        "destornillador",
        "llave",
    ],

    # --------------------------------------------------------
    # Medición / laboratorio
    # --------------------------------------------------------
    "medicion": [
        "termometro",
        "termómetro",
        "camara termica",
        "cámara térmica",
        "multimetro",
        "multímetro",
        "analizador",
        "horiba",
    ],
}


# ============================================================
# PERFILES CONVERSACIONALES
# ============================================================
# Define:
# - qué atributos son importantes
# - qué preguntas tienen valor comercial/técnico
#
# IMPORTANTE:
# NO significa que TODOS sean obligatorios.
# ============================================================

CATEGORY_PROFILES: Dict[str, Dict[str, Any]] = {

    # --------------------------------------------------------
    # Sensores
    # --------------------------------------------------------
    "sensor": {

        # Solo pedimos datos realmente críticos
        "required": [
            "subtipo",
        ],

        "priority": [
            "rango",
            "salida",
            "conexion",
            "marca",
        ],

        "questions": {

            "subtipo": (
                "¿El sensor es para presión, temperatura, nivel o caudal?"
            ),

            "rango": (
                "¿Qué rango necesitas? Ej: 0-10 bar, 0-100 psi."
            ),

            "salida": (
                "¿Qué salida necesitas? Ej: 4-20 mA, PNP, NPN o 0-10V."
            ),

            "conexion": (
                "¿Qué tipo de conexión o rosca necesitas?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # Motores
    # --------------------------------------------------------
    "motor": {

        "required": [
            "potencia",
        ],

        "priority": [
            "voltaje",
            "rpm",
            "marca",
        ],

        "questions": {

            "potencia": (
                "¿Qué potencia necesitas? Ej: 1HP, 5HP o 10HP."
            ),

            "voltaje": (
                "¿Qué voltaje necesitas? Ej: 220V o 440V."
            ),

            "rpm": (
                "¿Qué velocidad o RPM necesitas?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # Variadores
    # --------------------------------------------------------
    "variador": {

        "required": [
            "potencia",
        ],

        "priority": [
            "voltaje",
            "marca",
        ],

        "questions": {

            "potencia": (
                "¿Qué potencia debe manejar el variador?"
            ),

            "voltaje": (
                "¿Qué alimentación necesitas? Ej: 220V o 440V."
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # PLC / automatización
    # --------------------------------------------------------
    "plc": {

        "required": [],

        "priority": [
            "entradas",
            "salidas",
            "comunicacion",
            "marca",
        ],

        "questions": {

            "entradas": (
                "¿Cuántas entradas necesitas aproximadamente?"
            ),

            "salidas": (
                "¿Cuántas salidas necesitas aproximadamente?"
            ),

            "comunicacion": (
                "¿Necesitas Ethernet, Modbus, RS485 u otra comunicación?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # Eléctrico
    # --------------------------------------------------------
    "electrico": {

        "required": [],

        "priority": [
            "voltaje",
            "corriente",
            "marca",
        ],

        "questions": {

            "voltaje": (
                "¿Qué voltaje necesita el equipo?"
            ),

            "corriente": (
                "¿Qué corriente nominal necesitas?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # Válvulas / neumática
    # --------------------------------------------------------
    "valvula": {

        "required": [],

        "priority": [
            "tipo_accion",
            "diametro",
            "voltaje",
            "marca",
        ],

        "questions": {

            "tipo_accion": (
                "¿La válvula es neumática, eléctrica o manual?"
            ),

            "diametro": (
                "¿Qué diámetro necesitas?"
            ),

            "voltaje": (
                "¿Qué voltaje necesita?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # Herramientas
    # --------------------------------------------------------
    "herramienta": {

        "required": [],

        "priority": [
            "aplicacion",
            "medida",
            "marca",
        ],

        "questions": {

            "aplicacion": (
                "¿Para qué aplicación o trabajo la necesitas?"
            ),

            "medida": (
                "¿Qué medida o capacidad necesitas?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },

    # --------------------------------------------------------
    # Medición
    # --------------------------------------------------------
    "medicion": {

        "required": [],

        "priority": [
            "rango",
            "precision",
            "marca",
        ],

        "questions": {

            "rango": (
                "¿Qué rango de medición necesitas?"
            ),

            "precision": (
                "¿Qué nivel de precisión necesitas?"
            ),

            "marca": (
                "¿Tienes alguna marca de preferencia?"
            ),
        },
    },
}


# ============================================================
# PERFIL GENÉRICO
# ============================================================

GENERIC_PROFILE = {

    "required": [],

    "priority": [
        "marca",
        "referencia",
        "aplicacion",
    ],

    "questions": {

        "marca": (
            "¿Tienes alguna marca de preferencia?"
        ),

        "referencia": (
            "¿Tienes alguna referencia o código?"
        ),

        "aplicacion": (
            "¿Para qué aplicación necesitas el producto?"
        ),
    },
}


# ============================================================
# UTILIDADES
# ============================================================

def _normalize(text: str) -> str:
    """
    Normalización básica.
    """

    text = text or ""

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _contains_any(
    text: str,
    keywords: List[str],
) -> bool:
    """
    Verifica si contiene alguna keyword.
    """

    return any(
        keyword in text
        for keyword in keywords
    )


# ============================================================
# DETECCIÓN DE CATEGORÍA
# ============================================================

def detect_category(
    text: str
) -> Optional[str]:
    """
    Detecta categoría conversacional.
    """

    normalized = _normalize(text)

    for category, keywords in CATEGORY_KEYWORDS.items():

        if _contains_any(
            normalized,
            keywords,
        ):
            return category

    return None


# ============================================================
# OBTENER PERFIL
# ============================================================

def get_profile(
    category: Optional[str]
) -> Dict[str, Any]:
    """
    Obtiene perfil conversacional.
    """

    if not category:
        return GENERIC_PROFILE

    return CATEGORY_PROFILES.get(
        category,
        GENERIC_PROFILE,
    )


# ============================================================
# CONTEXTO FALTANTE
# ============================================================

def get_missing_fields(
    category: Optional[str],
    context: Dict[str, Any],
) -> List[str]:
    """
    Detecta atributos faltantes.
    """

    profile = get_profile(category)

    required = profile.get(
        "required",
        [],
    )

    missing = []

    for field in required:

        value = context.get(field)

        if value in [
            None,
            "",
            [],
            {},
        ]:
            missing.append(field)

    return missing


# ============================================================
# CONTROL DE PREGUNTAS
# ============================================================

def max_questions_reached(
    questions_asked: int
) -> bool:
    """
    Límite máximo de preguntas técnicas.
    """

    return questions_asked >= MAX_QUESTIONS


# ============================================================
# SIGUIENTE PREGUNTA
# ============================================================

def next_question(
    category: Optional[str],
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Decide siguiente pregunta relevante.
    """

    profile = get_profile(category)

    questions = profile.get(
        "questions",
        {},
    )

    priority = profile.get(
        "priority",
        [],
    )

    # --------------------------------------------------------
    # Buscar primer atributo faltante
    # --------------------------------------------------------
    for field in priority:

        value = context.get(field)

        if value in [
            None,
            "",
            [],
            {},
        ]:

            question = questions.get(field)

            if question:

                return {
                    "field": field,
                    "question": question,
                    "category": category,
                }

    return None


# ============================================================
# DECISIÓN PRINCIPAL
# ============================================================

def analyze_message(
    message: str,
    session_context: Optional[Dict[str, Any]] = None,
    questions_asked: int = 0,
) -> Dict[str, Any]:
    """
    Motor principal de decisión conversacional.
    """

    session_context = session_context or {}

    normalized = _normalize(message)

    # --------------------------------------------------------
    # Detectar categoría
    # --------------------------------------------------------
    category = (
        session_context.get("categoria")
        or detect_category(normalized)
        or session_context.get("familia")
    )

    # --------------------------------------------------------
    # Si NO detectamos categoría
    # NO forzamos demasiadas preguntas.
    # --------------------------------------------------------
    if not category:

        if max_questions_reached(
            questions_asked
        ):
            return {
                "action": "search",
                "context": session_context,
                "reason": "max_questions_unknown_category",
            }

        return {
            "action": "ask",
            "question": {
                "field": "general",
                "question": (
                    "¿Me puedes dar más detalle del producto "
                    "que necesitas? Por ejemplo marca, "
                    "referencia o aplicación."
                ),
                "category": "general",
            },
            "context": session_context,
            "reason": "unknown_category",
        }

    # --------------------------------------------------------
    # Verificar campos críticos faltantes
    # --------------------------------------------------------
    missing = get_missing_fields(
        category,
        session_context,
    )

    # --------------------------------------------------------
    # Si faltan datos pero ya llegamos al límite
    # hacemos retrieval igualmente.
    # --------------------------------------------------------
    if (
        missing
        and max_questions_reached(
            questions_asked
        )
    ):

        return {
            "action": "search",
            "context": session_context,
            "reason": "max_questions_reached",
        }

    # --------------------------------------------------------
    # Preguntar siguiente dato útil
    # --------------------------------------------------------
    question = next_question(
        category,
        session_context,
    )

    if (
        question
        and not max_questions_reached(
            questions_asked
        )
    ):

        return {
            "action": "ask",
            "question": question,
            "context": session_context,
            "reason": "need_more_context",
        }

    # --------------------------------------------------------
    # Contexto suficiente
    # --------------------------------------------------------
    return {
        "action": "search",
        "context": session_context,
        "reason": "ready_for_search",
    }


# ============================================================
# DEBUG
# ============================================================

def explain_category(
    category: str
) -> Dict[str, Any]:
    """
    Expone configuración de categoría.
    """

    profile = get_profile(category)

    return {
        "category": category,
        "profile": profile,
        "exists": category in CATEGORY_PROFILES,
    }