# ============================================================
# orchestration/commercial_continuity.py
# ============================================================
# RESPONSABILIDAD:
# Detectar continuidad comercial.
#
# Casos que resuelve:
# - Usuario ya seleccionó un producto.
# - Luego dice: "Envíame una cotización".
# - NIA debe continuar con ese producto.
# - NIA NO debe buscar productos nuevos con la frase "cotización".
#
# Mejora clave:
# - Si el usuario escribe un código explícito dentro del mensaje
#   de cotización, ese código manda sobre el producto activo.
#
# Ejemplo:
# - NIA muestra lista:
#   1. P101722
#   2. P256146
# - Usuario:
#   "Quiero cotizar: ... (Código: P256146)"
# - NIA debe cotizar P256146, NO P101722.
#
# Este módulo NO llama OpenAI.
# Este módulo NO inventa productos.
# Este módulo solo:
# - detecta continuidad comercial
# - recupera producto real desde memoria o código exacto
# - construye una respuesta de cotización segura
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

from memory.conversation_memory import (
    get_last_selected_product,
    extract_exact_product_code,
)
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
    # Cotización directa
    "enviame una cotizacion",
    "enviame la cotizacion",
    "enviame cotizacion",
    "enviar cotizacion",
    "envia cotizacion",
    "envíame una cotización",
    "envíame la cotización",
    "envíame cotización",
    "mandame la cotizacion",
    "mándame la cotización",
    "mandame cotizacion",
    "mándame cotización",
    "me envias la cotizacion",
    "me envías la cotización",
    "me puedes enviar la cotizacion",
    "me puedes enviar la cotización",

    # Cotizar producto actual
    "quiero cotizar",
    "quiero cotizarlo",
    "quiero cotizar este producto",
    "quiero cotizar ese producto",
    "cotizar este producto",
    "cotizar ese producto",
    "cotizame este producto",
    "cotízame este producto",
    "cotizame ese producto",
    "cotízame ese producto",
    "me puedes cotizar este producto",
    "me puedes cotizar ese producto",
    "me cotizas este producto",
    "me cotizas ese producto",

    # Botón / intención comercial
    "solicitar cotizacion",
    "solicitar cotización",
    "generar cotizacion",
    "generar cotización",
    "hazme la cotizacion",
    "hazme la cotización",
    "me haces la cotizacion",
    "me haces la cotización",

    # Compra / cierre
    "quiero comprarlo",
    "quiero comprar",
    "me interesa",
    "lo quiero",
    "procedamos",
    "dale",

    # Referencias al producto activo
    "si ese",
    "sí ese",
    "ese producto",
    "este producto",
    "ese mismo",
    "este mismo",
    "con ese",
    "con este",
]


def is_commercial_continuation_message(message: str) -> bool:
    """
    Detecta si el mensaje es una continuación comercial.

    Importante:
    No significa buscar productos.
    Significa continuar con producto activo o con código explícito.
    """
    text = _normalize(message)

    if not text:
        return False

    if any(_normalize(phrase) in text for phrase in COMMERCIAL_CONTINUITY_PHRASES):
        return True

    # Caso flexible:
    # "cotización", "cotizacion", "enviar cotización"
    # sin una solicitud nueva de producto.
    if "cotizacion" in text:
        return True

    # Respuestas cortas de continuación luego de una recomendación.
    if text in {
        "si",
        "sí",
        "ok",
        "listo",
        "dale",
        "correcto",
        "ese",
        "este",
        "ese mismo",
        "este mismo",
    }:
        return True

    return False


# ============================================================
# RECUPERACIÓN DE PRODUCTO
# ============================================================

def _format_selected_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza el producto seleccionado usando el formateador oficial.

    Esto conserva:
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


def _extract_code_from_message(message: str) -> Optional[str]:
    """
    Extrae un código explícito desde el mensaje del usuario.

    Ejemplos:
    - Código: P256146
    - codigo 300203
    - quiero cotizar P256146
    - producto 300203
    """
    code = extract_exact_product_code(message)

    if code:
        return _safe_str(code)

    # Fallback adicional para formatos tipo:
    # "(Código: P256146)" o "codigo:P256146"
    raw = str(message or "")

    match = re.search(
        r"(?:codigo|código|cod|cód)\s*[:#-]?\s*([Pp]?\d{5,}[A-Za-z0-9]*)",
        raw,
        flags=re.IGNORECASE,
    )

    if match:
        code = match.group(1).strip()

        if code:
            return code.upper() if code.lower().startswith("p") else code

    return None


def _search_product_by_code(code: str) -> Optional[Dict[str, Any]]:
    """
    Busca un producto real por código exacto.
    """
    code = _safe_str(code)

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


def _extract_code_from_context(session: Dict[str, Any]) -> Optional[str]:
    """
    Intenta obtener código desde contexto/memoria.
    """
    context = session.get("context", {})

    if not isinstance(context, dict):
        context = {}

    code = (
        context.get("codigo_producto")
        or context.get("referencia")
        or session.get("last_selected_product_code")
    )

    code = _safe_str(code)

    return code or None


def _recover_product_from_context_code(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Recupera producto desde código guardado en contexto.
    """
    code = _extract_code_from_context(session)

    if not code:
        return None

    return _search_product_by_code(code)


def _get_active_product_for_continuity(
    session: Dict[str, Any],
    message: str,
) -> Optional[Dict[str, Any]]:
    """
    Obtiene producto activo para continuidad comercial.

    Orden correcto:
    1. Código explícito en el mensaje del usuario.
       Este tiene máxima prioridad.
    2. last_selected_product.
    3. código en contexto / referencia / last_selected_product_code.
    """
    explicit_code = _extract_code_from_message(message)

    if explicit_code:
        product_from_message = _search_product_by_code(explicit_code)

        if product_from_message:
            return product_from_message

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

    selected_product = _get_active_product_for_continuity(
        session=session,
        message=message,
    )

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
        "Claro. Puedo ayudarte a iniciar la cotización del producto que quieres.\n\n"
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