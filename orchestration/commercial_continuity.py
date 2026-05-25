# ============================================================
# orchestration/commercial_continuity.py
# ============================================================
# RESPONSABILIDAD:
# Detectar continuidad comercial.
#
# Caso que resuelve:
# - Usuario ya seleccionó un producto.
# - Luego dice: "Envíame una cotización".
# - NIA debe continuar con ese producto.
# - NIA NO debe buscar productos nuevos con la frase "cotización".
#
# Este módulo NO busca en MongoDB.
# Este módulo NO llama OpenAI.
# Este módulo NO inventa productos.
#
# Importante:
# Para conservar precio, disponibilidad, referencia y campos limpios,
# este módulo usa services.search.formatear_producto(), igual que
# core/response_engine.py.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

from memory.conversation_memory import get_last_selected_product
from services.search import formatear_producto


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


def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte a texto seguro.
    """
    if value is None:
        return default

    try:
        value = str(value).strip()
        return value if value else default
    except Exception:
        return default


# ============================================================
# DETECCIÓN DE CONTINUIDAD COMERCIAL
# ============================================================

COMMERCIAL_CONTINUITY_PHRASES = [
    "enviame una cotizacion",
    "enviame cotizacion",
    "enviar cotizacion",
    "envia cotizacion",
    "envíame una cotización",
    "envíame cotización",
    "quiero cotizar",
    "quiero cotizarlo",
    "quiero cotizar este producto",
    "cotizar este producto",
    "solicitar cotizacion",
    "solicitar cotización",
    "generar cotizacion",
    "generar cotización",
    "hazme la cotizacion",
    "hazme la cotización",
    "me haces la cotizacion",
    "me haces la cotización",
    "quiero comprarlo",
    "quiero comprar",
    "me interesa",
    "lo quiero",
    "procedamos",
    "dale",
    "si ese",
    "sí ese",
    "ese producto",
    "ese mismo",
    "con ese",
]


def is_commercial_continuation_message(message: str) -> bool:
    """
    Detecta si el mensaje es una continuación comercial.

    Importante:
    No significa buscar productos.
    Significa continuar con el último producto seleccionado.
    """
    text = _normalize(message)

    if not text:
        return False

    if any(_normalize(phrase) in text for phrase in COMMERCIAL_CONTINUITY_PHRASES):
        return True

    # Caso flexible:
    # "cotización", "cotizacion", "enviar cotización"
    # sin producto nuevo explícito.
    if "cotizacion" in text and not any(
        token in text
        for token in [
            "sensor",
            "motor",
            "variador",
            "plc",
            "valvula",
            "torquimetro",
            "producto ",
            "codigo",
            "referencia",
            "marca",
        ]
    ):
        return True

    # Respuestas cortas de continuación luego de una recomendación.
    if text in {"si", "sí", "ok", "listo", "dale", "correcto", "ese", "ese mismo"}:
        return True

    return False


# ============================================================
# FORMATO DE PRODUCTO
# ============================================================

def _format_selected_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza el producto seleccionado usando el formateador oficial
    de productos.

    Esto evita perder:
    - precio
    - disponibilidad
    - tiempo de entrega
    - referencia
    - características
    """
    if not isinstance(product, dict):
        return {}

    try:
        formatted = formatear_producto(product)

        if isinstance(formatted, dict) and formatted:
            return formatted

    except Exception:
        pass

    return product


def _product_code(product: Dict[str, Any]) -> str:
    return _safe_str(product.get("codigo") or product.get("CODIGO"))


def _product_name(product: Dict[str, Any]) -> str:
    return _safe_str(
        product.get("nombre")
        or product.get("DESCRIPCION_CORTA_PRE")
        or product.get("descripcion")
    )


def _product_brand(product: Dict[str, Any]) -> str:
    return _safe_str(product.get("marca") or product.get("MARCA_LET"))


def _product_price(product: Dict[str, Any]) -> str:
    return _safe_str(
        product.get("precio")
        or product.get("PRECIO")
        or product.get("precio_formateado"),
        "Consultarnos",
    )


def _product_availability(product: Dict[str, Any]) -> str:
    return _safe_str(
        product.get("disponibilidad")
        or product.get("DISPONIBILIDAD")
        or product.get("stock")
        or product.get("STOCK"),
        "Consultar disponibilidad",
    )


def _product_delivery(product: Dict[str, Any]) -> str:
    return _safe_str(
        product.get("tiempo_entrega")
        or product.get("TIEMPO_ENTREGA")
        or product.get("entrega")
    )


# ============================================================
# CONSTRUCCIÓN DE RESPUESTA
# ============================================================

def build_commercial_continuity_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Optional[Dict[str, Any]]:
    """
    Si el mensaje es continuidad comercial y hay producto seleccionado,
    construye respuesta sin buscar productos nuevos.
    """
    if not is_commercial_continuation_message(message):
        return None

    selected_product = get_last_selected_product(session)

    if not selected_product:
        return None

    selected_product = _format_selected_product(selected_product)

    codigo = _product_code(selected_product)
    nombre = _product_name(selected_product)
    marca = _product_brand(selected_product)
    precio = _product_price(selected_product)
    disponibilidad = _product_availability(selected_product)
    tiempo_entrega = _product_delivery(selected_product)

    disponibilidad_txt = disponibilidad

    if tiempo_entrega and tiempo_entrega not in disponibilidad_txt:
        disponibilidad_txt = f"{disponibilidad} · {tiempo_entrega}"

    response = (
        "Claro. Puedo ayudarte a iniciar la cotización del producto seleccionado:\n\n"
        f"**Producto:** {nombre or 'Producto seleccionado'}\n"
        f"**Código:** {codigo or 'Sin código disponible'}\n"
        f"**Marca:** {marca or 'No especificada'}\n"
        f"**Precio:** {precio}\n"
        f"**Disponibilidad:** {disponibilidad_txt}\n\n"
        "Para continuar con la cotización, ¿me confirmas nombre, empresa, "
        "correo o teléfono de contacto?"
    )

    return {
        "intent": detected_intent,
        "response": response,
        "needs_clarification": True,
        "context": session.get("context", {}),
        "session_id": session.get("session_id"),
        "decision_reason": "commercial_continuity_last_selected_product",
        "compatible_count": 1,
        "requires_customer_data": True,
        "estado_negociacion": "cotizacion_en_proceso",
        "cards": [selected_product],
        "results": [selected_product],
    }