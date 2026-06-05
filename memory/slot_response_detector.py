# ============================================================
# memory/slot_response_detector.py
# ============================================================
# RESPONSABILIDAD:
# Detectar si el mensaje del usuario responde al último slot
# preguntado por NIA.
#
# Este módulo NO busca productos.
# Este módulo NO llama OpenAI.
# Este módulo NO inventa datos.
# Este módulo NO clasifica por familias manuales.
# Este módulo NO usa marcas manuales.
# Este módulo NO decide el flujo comercial.
#
# Solo interpreta respuestas claras del usuario frente a una
# pregunta activa de NIA.
#
# Ejemplo:
# - NIA pregunta: ¿Qué profundidad máxima necesitas medir?
# - slot pendiente: technical_clarification
# - Usuario responde: 100 metros
# - Resultado:
#   {
#       "matched": True,
#       "context": {"technical_clarification": "100 metros"},
#       "clear_pending_slot": True
#   }
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
    - minúsculas;
    - sin acentos;
    - espacios limpios.
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text).strip()


def _safe_text(message: Any) -> str:
    """
    Convierte mensaje a texto seguro sin perder el valor original.
    """
    if message in [None, "", [], {}]:
        return ""

    try:
        return str(message).strip()
    except Exception:
        return ""


def _text_response(message: Any) -> Dict[str, Any]:
    """
    Devuelve una respuesta textual simple.

    Se usa para slots donde NIA preguntó algo explícito y la respuesta
    del usuario debe guardarse sin clasificar manualmente.
    """
    text = _safe_text(message)

    if not text:
        return {}

    return {
        "value": text,
    }


# ============================================================
# RESPUESTAS NEGATIVAS / DESCONOCIDAS
# ============================================================

NEGATIVE_OR_UNKNOWN_TERMS = [
    "no se",
    "no sé",
    "no tengo",
    "no conozco",
    "no recuerdo",
    "no importa",
    "cualquiera",
    "me da igual",
    "no sabria",
    "no sabría",
    "no estoy seguro",
    "no estoy segura",
    "no tengo ese dato",
    "aun no se",
    "aún no sé",
]


def is_negative_or_unknown_response(message: str) -> bool:
    """
    Detecta respuestas donde el usuario indica que no sabe,
    no tiene preferencia o no cuenta con ese dato.

    Nota:
    No usamos "no" solo como término aislado porque puede aparecer en
    frases válidas y generar falsos positivos.
    """
    text = _normalize(message)

    if not text:
        return False

    return any(term in text for term in [_normalize(t) for t in NEGATIVE_OR_UNKNOWN_TERMS])


# ============================================================
# DETECTORES POR SLOT
# ============================================================

def _detect_subtipo_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'subtipo'.

    No clasifica familias ni subtipos por listas manuales.
    Guarda literalmente lo que el usuario respondió.
    """
    if is_negative_or_unknown_response(message):
        return {
            "subtipo": "unknown",
            "generic_need_status": "unknown",
        }

    text = _safe_text(message)

    if not text:
        return {}

    return {
        "subtipo": text,
    }


def _detect_marca_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'marca'.

    No usa lista de marcas.
    Si el usuario escribe una marca, se guarda textual.
    """
    if is_negative_or_unknown_response(message):
        return {
            "marca_descartada": True,
            "brand_preference_status": "no_preference",
        }

    text = _safe_text(message)

    if not text:
        return {}

    return {
        "marca": text,
        "brand_preference_status": "provided",
    }


def _detect_referencia_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'referencia'.
    """
    if is_negative_or_unknown_response(message):
        return {
            "referencia_descartada": True,
            "reference_status": "unknown",
        }

    text = _safe_text(message)

    if not text:
        return {}

    return {
        "referencia": text,
    }


def _detect_aplicacion_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta al slot 'aplicacion'.
    """
    if is_negative_or_unknown_response(message):
        return {
            "aplicacion_descartada": True,
            "application_status": "unknown",
        }

    text = _safe_text(message)

    if not text:
        return {}

    return {
        "aplicacion": text,
    }


def _detect_technical_clarification_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta una respuesta a una pregunta técnica dinámica.

    Este slot se usa cuando NIA no tiene certeza suficiente para recomendar
    y genera una pregunta técnica con OpenAI.

    Ejemplos válidos:
    - "100 metros"
    - "0 a 10 bar"
    - "RS485"
    - "agua limpia"
    - "medición continua"
    - "pozo profundo"

    No intenta clasificar la respuesta.
    No inventa estructura.
    Guarda la respuesta textual como technical_clarification para que el
    orquestador la use en la siguiente búsqueda.
    """
    if is_negative_or_unknown_response(message):
        return {
            "technical_clarification": "unknown",
            "generic_need_status": "unknown",
        }

    text = _safe_text(message)

    if not text:
        return {}

    return {
        "technical_clarification": text,
    }


def _detect_generic_product_or_application_answer(message: str) -> Dict[str, Any]:
    """
    Interpreta respuesta cuando NIA preguntó:
    ¿Qué producto buscas o para qué aplicación lo necesitas?

    Importante:
    - No detecta familias.
    - No clasifica por listas manuales.
    - No asigna subtipo automático.
    - Guarda la necesidad como aplicación/texto libre.
    """
    if is_negative_or_unknown_response(message):
        return {
            "generic_need_status": "unknown",
        }

    text = _safe_text(message)

    if not text:
        return {}

    return {
        "aplicacion": text,
    }


def _detect_simple_slot_answer(
    message: str,
    slot_name: str,
    unknown_status_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Detector genérico para slots simples.

    Guarda el texto del usuario en el campo correspondiente.
    """
    if is_negative_or_unknown_response(message):
        result: Dict[str, Any] = {
            slot_name: "unknown",
        }

        if unknown_status_key:
            result[unknown_status_key] = "unknown"

        return result

    text = _safe_text(message)

    if not text:
        return {}

    return {
        slot_name: text,
    }


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

    previous_context se conserva por compatibilidad, pero este módulo ya no
    usa familias manuales para interpretar respuestas.
    """
    _ = previous_context or {}

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
        detected = _detect_subtipo_answer(message)

    elif slot == "marca":
        detected = _detect_marca_answer(message)

    elif slot == "referencia":
        detected = _detect_referencia_answer(message)

    elif slot == "aplicacion":
        detected = _detect_aplicacion_answer(message)

    elif slot == "technical_clarification":
        detected = _detect_technical_clarification_answer(message)

    elif slot in ["producto_o_aplicacion", "generic_product_or_application"]:
        detected = _detect_generic_product_or_application_answer(message)

    elif slot == "medida":
        detected = _detect_simple_slot_answer(message, "medida")

    elif slot == "voltaje":
        detected = _detect_simple_slot_answer(message, "voltaje")

    elif slot == "potencia":
        detected = _detect_simple_slot_answer(message, "potencia")

    elif slot == "rango":
        detected = _detect_simple_slot_answer(message, "rango")

    elif slot == "comunicacion":
        detected = _detect_simple_slot_answer(message, "comunicacion")

    elif slot == "presion":
        detected = _detect_simple_slot_answer(message, "presion")

    elif slot == "temperatura":
        detected = _detect_simple_slot_answer(message, "temperatura")

    elif slot == "caudal":
        detected = _detect_simple_slot_answer(message, "caudal")

    elif slot == "nivel":
        detected = _detect_simple_slot_answer(message, "nivel")

    elif slot == "tipo_accion":
        detected = _detect_simple_slot_answer(message, "tipo_accion")

    elif slot == "fluido":
        detected = _detect_simple_slot_answer(message, "fluido")

    elif slot == "salida":
        detected = _detect_simple_slot_answer(message, "salida")

    elif slot == "diametro":
        detected = _detect_simple_slot_answer(message, "diametro")

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