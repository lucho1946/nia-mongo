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
# Este módulo NO llama OpenAI.
# Este módulo NO inventa productos.
#
# Mejora actual:
# - Si no existe last_selected_product, intenta recuperar producto
#   desde context.codigo_producto / context.referencia.
# - Esto protege flujos donde el cliente corrige código o pide
#   cotización después de haber mencionado un código exacto.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

from memory.conversation_memory import get_last_selected_product
from retrieval.search_adapter import search_exact_code
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

    if text in {"si", "sí", "ok", "listo", "dale", "correcto", "ese", "ese mismo"}:
        return True

    return False


# ============================================================
# RECUPERACIÓN DE PRODUCTO ACTIVO
# ============================================================

def _format_selected_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza el producto seleccionado usando el formateador oficial.
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


def _extract_code_from_context(session: Dict[str, Any]) -> Optional[str]:
    """
    Intenta obtener código desde el contexto actual de la sesión.
    """
    context = session.get("context", {})

    if not isinstance(context, dict):
        return None

    code = (
        context.get("codigo_producto")
        or context.get("referencia")
        or session.get("last_selected_product_code")
    )

    code = _safe_str(code)

    return code or None


def _recover_product_from_context_code(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Recupera producto desde código exacto guardado en contexto.

    Esto es un fallback de seguridad para continuidad comercial.
    """
    code = _extract_code_from_context(session)

    if not code:
        return None

    try:
        results = search_exact_code(code)
    except Exception:
        return None

    if not results:
        return None

    first = results[0]

    if not isinstance(first, dict):
        return None

    return first


def _get_active_product_for_continuity(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Obtiene producto activo para continuidad comercial.

    Orden:
    1. last_selected_product
    2. código en contexto / referencia / last_selected_product_code
    """
    selected_product = get_last_selected_product(session)

    if selected_product:
        return selected_product

    recovered = _recover_product_from_context_code(session)

    if recovered:
        return recovered

    return None


# ============================================================
# CAMPOS DE PRODUCTO
# ============================================================

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

    selected_product = _get_active_product_for_continuity(session)

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
        f"Producto: {nombre or 'Producto seleccionado'}\n"
        f"Código: {codigo or 'Sin código disponible'}\n"
        f"Marca: {marca or 'No especificada'}\n"
        f"Precio: {precio}\n"
        f"Disponibilidad: {disponibilidad_txt}\n\n"
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