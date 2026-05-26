# ============================================================
# memory/slot_response_detector.py
# ============================================================
# RESPONSABILIDAD:
# Detectar si el mensaje del usuario responde al último slot
# preguntado por NIA.
#
# Ejemplo:
# - NIA pregunta: ¿Qué tipo específico necesitas?
# - slot pendiente: subtipo
# - Usuario responde: sensor fotoeléctrico
# - Resultado:
#   {
#       "matched": True,
#       "context": {"familia": "sensor", "subtipo": "fotoelectrico"}
#   }
#
# Este módulo NO busca productos.
# Este módulo NO llama OpenAI.
# Este módulo NO inventa datos.
# Solo interpreta respuestas claras del usuario.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional


# ============================================================
# UTILIDADES
# ============================================================

def _normalize(text: Any) -> str:
    """
    Normaliza texto:
    - minúsculas
    - sin acentos
    - espacios limpios
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text)


def _has_any(text: str, terms: list[str]) -> bool:
    """
    Verifica si el texto contiene cualquiera de los términos.
    """
    return any(term in text for term in terms)


# ============================================================
# RESPUESTAS NEGATIVAS / DESCONOCIDAS
# ============================================================

NEGATIVE_OR_UNKNOWN_TERMS = [
    "no",
    "no se",
    "no sé",
    "no tengo",
    "no tengo ninguna",
    "no tengo ninguna marca",
    "no conozco",
    "no recuerdo",
    "no importa",
    "cualquiera",
    "sin marca",
    "sin referencia",
    "me da igual",
    "la marca no importa",
]


def is_negative_or_unknown_response(message: str) -> bool:
    """
    Detecta respuestas donde el usuario indica que no sabe,
    no tiene preferencia o no cuenta con ese dato.
    """
    text = _normalize(message)

    if not text:
        return False

    return any(term in text for term in NEGATIVE_OR_UNKNOWN_TERMS)


# ============================================================
# SUBTIPOS INDUSTRIALES
# ============================================================

SENSOR_SUBTYPE_TERMS: Dict[str, list[str]] = {
    "fotoelectrico": [
        "fotoelectrico",
        "foto electrico",
        "fotoeléctrico",
        "foto eléctrico",
        "fotocelda",
        "foto celda",
        "sensor fotoelectrico",
        "sensor foto electrico",
        "sensor fotoeléctrico",
        "sensor foto eléctrico",
    ],
    "inductivo": [
        "inductivo",
        "sensor inductivo",
        "proximidad inductivo",
        "proximidad inductiva",
    ],
    "capacitivo": [
        "capacitivo",
        "sensor capacitivo",
        "proximidad capacitivo",
        "proximidad capacitiva",
    ],
    "reflectivo": [
        "reflectivo",
        "retroreflectivo",
        "retro reflectivo",
        "reflex",
        "reflector",
    ],
    "barrera": [
        "barrera",
        "tipo barrera",
        "emisor receptor",
        "emisor y receptor",
    ],
    "difuso": [
        "difuso",
        "difusa",
        "deteccion difusa",
        "detección difusa",
    ],
    "presion": [
        "presion",
        "presión",
        "sensor de presion",
        "sensor de presión",
        "transmisor de presion",
        "transmisor de presión",
    ],
    "temperatura": [
        "temperatura",
        "sensor de temperatura",
        "termocupla",
        "pt100",
        "rtd",
    ],
    "nivel": [
        "nivel",
        "sensor de nivel",
    ],
    "caudal": [
        "caudal",
        "flujo",
        "sensor de caudal",
    ],
}


def detect_sensor_subtype(message: str) -> Optional[str]:
    """
    Detecta subtipo de sensor a partir de lenguaje natural.
    """
    text = _normalize(message)

    for subtype, terms in SENSOR_SUBTYPE_TERMS.items():
        normalized_terms = [_normalize(term) for term in terms]

        if _has_any(text, normalized_terms):
            return subtype

    return None


# ============================================================
# DETECTORES POR SLOT
# ============================================================

def _detect_subtipo_answer(message: str, previous_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'subtipo'.
    """
    text = _normalize(message)
    detected: Dict[str, Any] = {}

    sensor_subtype = detect_sensor_subtype(message)

    if sensor_subtype:
        detected["familia"] = "sensor"
        detected["subtipo"] = sensor_subtype

        # Señales adicionales útiles.
        if sensor_subtype == "presion":
            detected["presion"] = message.strip()

        if sensor_subtype == "temperatura":
            detected["temperatura"] = message.strip()

        if sensor_subtype == "nivel":
            detected["nivel"] = message.strip()

        if sensor_subtype == "caudal":
            detected["caudal"] = message.strip()

        return detected

    # Si ya veníamos hablando de sensor y el usuario responde con
    # "fotoeléctrico", "inductivo", etc., los términos anteriores ya cubren.
    # Si responde algo genérico, guardamos como subtipo textual seguro.
    if previous_context.get("familia") == "sensor" and text:
        detected["familia"] = "sensor"
        detected["subtipo"] = text
        return detected

    return detected


def _detect_marca_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'marca'.
    """
    text = _normalize(message)

    if is_negative_or_unknown_response(message):
        return {
            "marca_descartada": True,
            "brand_preference_status": "no_preference",
        }

    # Si no es negativa, dejamos que conversation_memory extraiga marca
    # desde su lista conocida. Aquí no inventamos marcas.
    if text:
        return {
            "marca": message.strip(),
            "brand_preference_status": "provided",
        }

    return {}


def _detect_referencia_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'referencia'.
    """
    if is_negative_or_unknown_response(message):
        return {
            "referencia_descartada": True,
            "reference_status": "unknown",
        }

    text = str(message or "").strip()

    if text:
        return {
            "referencia": text,
        }

    return {}


def _detect_aplicacion_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'aplicacion'.
    """
    if is_negative_or_unknown_response(message):
        return {
            "aplicacion_descartada": True,
            "application_status": "unknown",
        }

    text = str(message or "").strip()

    if text:
        return {
            "aplicacion": text,
        }

    return {}


def _detect_generic_product_or_application_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta respuesta cuando NIA preguntó:
    ¿Qué producto buscas o para qué aplicación lo necesitas?
    """
    text = _normalize(message)

    if is_negative_or_unknown_response(message):
        return {
            "generic_need_status": "unknown",
        }

    detected: Dict[str, Any] = {}

    # Familias comunes.
    if "sensor" in text:
        detected["familia"] = "sensor"

    elif "variador" in text or "vfd" in text or "drive" in text:
        detected["familia"] = "variador"

    elif "plc" in text:
        detected["familia"] = "plc"

    elif "motorreductor" in text or "motor reductor" in text:
        detected["familia"] = "motorreductor"

    elif "motor" in text:
        detected["familia"] = "motor"

    elif "valvula" in text or "válvula" in text:
        detected["familia"] = "valvula"

    elif "torquimetro" in text or "torquímetro" in text:
        detected["familia"] = "herramienta"
        detected["subtipo"] = "torquimetro"

    # Subtipo de sensor.
    sensor_subtype = detect_sensor_subtype(message)

    if sensor_subtype:
        detected["familia"] = "sensor"
        detected["subtipo"] = sensor_subtype

    if not detected and text:
        detected["aplicacion"] = message.strip()

    return detected


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def detect_slot_response(
    message: str,
    pending_slot: Optional[str],
    previous_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Detecta si el mensaje responde al slot pendiente.

    Retorna:
    {
        "matched": bool,
        "slot": "...",
        "context": {...},
        "clear_pending_slot": bool
    }
    """
    previous_context = previous_context or {}
    slot = _normalize(pending_slot)

    if not slot:
        return {
            "matched": False,
            "slot": None,
            "context": {},
            "clear_pending_slot": False,
        }

    detected: Dict[str, Any] = {}

    if slot == "subtipo":
        detected = _detect_subtipo_answer(message, previous_context)

    elif slot == "marca":
        detected = _detect_marca_answer(message)

    elif slot == "referencia":
        detected = _detect_referencia_answer(message)

    elif slot == "aplicacion":
        detected = _detect_aplicacion_answer(message)

    elif slot in ["producto_o_aplicacion", "generic_product_or_application"]:
        detected = _detect_generic_product_or_application_answer(message)

    elif slot == "medida":
        # Medida/capacidad, por ejemplo: 200nm, 1/2", 10mm.
        text = str(message or "").strip()

        if text:
            detected = {
                "medida": text,
            }

    elif slot == "voltaje":
        text = str(message or "").strip()

        if text:
            detected = {
                "voltaje": text,
            }

    elif slot == "potencia":
        text = str(message or "").strip()

        if text:
            detected = {
                "potencia": text,
            }

    elif slot == "rango":
        text = str(message or "").strip()

        if text:
            detected = {
                "rango": text,
            }

    elif slot == "comunicacion":
        text = str(message or "").strip()

        if text:
            detected = {
                "comunicacion": text,
            }

    if detected:
        return {
            "matched": True,
            "slot": slot,
            "context": detected,
            "clear_pending_slot": True,
        }

    return {
        "matched": False,
        "slot": slot,
        "context": {},
        "clear_pending_slot": False,
    }