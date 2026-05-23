# ============================================================
# RESPONSE ENGINE — NIA OS
# ============================================================
# Responsabilidad:
# Convertir la intención + resultados de búsqueda en una
# respuesta útil, natural y comercial para el usuario.
#
# Este módulo NO busca productos.
# Este módulo NO decide intención.
# Este módulo SOLO transforma salida técnica en respuesta final.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.search import formatear_producto


# ============================================================
# UTILIDADES INTERNAS
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte cualquier valor a string de forma segura.
    """
    if value is None:
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def _normalize_results(search_payload: Dict[str, Any]) -> List[dict]:
    """
    Normaliza distintas formas de payload de búsqueda.

    Acepta:
    - {"results": [...]}
    - {"result": [...]}
    - {"result": {...}}
    - lista directa
    """
    if not search_payload:
        return []

    if isinstance(search_payload, list):
        return [x for x in search_payload if isinstance(x, dict)]

    if not isinstance(search_payload, dict):
        return []

    if isinstance(search_payload.get("results"), list):
        return [x for x in search_payload["results"] if isinstance(x, dict)]

    if isinstance(search_payload.get("result"), list):
        return [x for x in search_payload["result"] if isinstance(x, dict)]

    if isinstance(search_payload.get("result"), dict):
        return [search_payload["result"]]

    return []


def _format_price_short(product: dict) -> str:
    """
    Extrae el precio ya formateado si existe.
    """
    return _safe_str(product.get("precio"), "Consultar")


def _format_stock_short(product: dict) -> str:
    """
    Resume disponibilidad en una línea corta.
    """
    disp = _safe_str(product.get("disponibilidad"), "Consultar disponibilidad")
    tiempo = _safe_str(product.get("tiempo_entrega"), "")
    if tiempo:
        return f"{disp} · {tiempo}"
    return disp


def _build_product_card(product: dict) -> dict:
    """
    Estructura limpia para mostrar un producto al usuario.
    """
    return {
        "codigo": _safe_str(product.get("codigo")),
        "nombre": _safe_str(product.get("nombre")),
        "marca": _safe_str(product.get("marca")),
        "referencia": _safe_str(product.get("referencia")),
        "precio": _format_price_short(product),
        "disponibilidad": _format_stock_short(product),
        "nivel_1": _safe_str(product.get("nivel_1")),
        "nivel_2": _safe_str(product.get("nivel_2")),
        "equivalente": _safe_str(product.get("equivalente")),
        "equivalente_2": _safe_str(product.get("equivalente_2")),
        "caracteristicas": product.get("caracteristicas", []) if isinstance(product.get("caracteristicas", []), list) else [],
    }


def _summarize_top_products(products: List[dict], max_items: int = 3) -> str:
    """
    Genera un resumen textual corto de los mejores resultados.
    """
    if not products:
        return ""

    lines = []
    for idx, raw in enumerate(products[:max_items], start=1):
        formatted = formatear_producto(raw)
        nombre = _safe_str(formatted.get("nombre"))
        marca = _safe_str(formatted.get("marca"))
        precio = _format_price_short(formatted)
        codigo = _safe_str(formatted.get("codigo"))
        disp = _format_stock_short(formatted)

        partes = [f"{idx}. {nombre}"]
        if marca:
            partes.append(f"({marca})")
        if codigo:
            partes.append(f"- {codigo}")
        if precio:
            partes.append(f"- {precio}")
        if disp:
            partes.append(f"- {disp}")

        lines.append(" ".join(partes))

    return "\n".join(lines)


def _build_clarification_message(intent: str) -> str:
    """
    Mensaje por defecto cuando faltan datos.
    """
    if intent == "codigo_producto":
        return "Encontré el código, pero no pude recuperar información suficiente. ¿Me confirmas más detalle del producto?"
    if intent == "comercial":
        return "Claro, puedo ayudarte con cotización, precio o disponibilidad. ¿Qué producto necesitas?"
    if intent == "producto":
        return "¿Me das un poco más de detalle del producto que necesitas? Por ejemplo: marca, referencia, rango, voltaje o aplicación."
    return "¿Me puedes dar un poco más de detalle para ayudarte mejor?"


# ============================================================
# MOTOR PRINCIPAL DE RESPUESTA
# ============================================================

def generate_response(
    intent_data: Dict[str, Any],
    search_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convierte la salida del router/retrieval en una respuesta final.

    Parámetros:
    - intent_data: resultado de detect_intent()
    - search_payload: salida de search_adapter / buscar_productos()

    Retorna un dict uniforme con:
    - intent
    - response
    - cards (opcional)
    - raw_count (opcional)
    """
    intent = _safe_str(intent_data.get("intent"), "general")

    # --------------------------------------------------------
    # 1) SALUDO
    # --------------------------------------------------------
    if intent == "saludo":
        return {
            "intent": intent,
            "response": "Hola, soy NIA. ¿Qué producto industrial necesitas?",
        }

    # --------------------------------------------------------
    # 2) COMERCIAL
    # --------------------------------------------------------
    if intent == "comercial":
        return {
            "intent": intent,
            "response": "Claro, puedo ayudarte con cotización, precio o disponibilidad. ¿Qué producto necesitas?",
        }

    # --------------------------------------------------------
    # 3) SIN PAYLOAD DE BÚSQUEDA
    # --------------------------------------------------------
    if not search_payload:
        return {
            "intent": intent,
            "response": _build_clarification_message(intent),
            "cards": [],
        }

    # --------------------------------------------------------
    # 4) NORMALIZAR RESULTADOS
    # --------------------------------------------------------
    raw_results = _normalize_results(search_payload)

    if not raw_results:
        return {
            "intent": intent,
            "response": _build_clarification_message(intent),
            "cards": [],
            "raw_count": 0,
        }

    # --------------------------------------------------------
    # 5) CÓDIGO EXACTO
    # --------------------------------------------------------
    if intent == "codigo_producto":
        product = formatear_producto(raw_results[0])
        card = _build_product_card(product)

        response = (
            f"Encontré el producto exacto: {card['nombre']}"
            + (f" | Marca: {card['marca']}" if card["marca"] else "")
            + (f" | Código: {card['codigo']}" if card["codigo"] else "")
            + (f" | Precio: {card['precio']}" if card["precio"] else "")
            + (f" | {card['disponibilidad']}" if card["disponibilidad"] else "")
        )

        return {
            "intent": intent,
            "response": response,
            "cards": [card],
            "raw_count": len(raw_results),
        }

    # --------------------------------------------------------
    # 6) PRODUCTO / GENERAL
    # --------------------------------------------------------
    formatted_results = [formatear_producto(p) for p in raw_results]
    cards = [_build_product_card(p) for p in formatted_results]

    top = cards[0]
    summary = _summarize_top_products(raw_results, max_items=3)

    if len(cards) == 1:
        response = (
            f"Encontré una opción para ti: {top['nombre']}"
            + (f" | Marca: {top['marca']}" if top["marca"] else "")
            + (f" | Precio: {top['precio']}" if top["precio"] else "")
            + (f" | {top['disponibilidad']}" if top["disponibilidad"] else "")
        )
    else:
        response = (
            "Encontré varias opciones relevantes. Te muestro las mejores:\n\n"
            f"{summary}\n\n"
            "Si quieres, puedo afinar por marca, referencia, rango o voltaje."
        )

    return {
        "intent": intent,
        "response": response,
        "cards": cards,
        "raw_count": len(cards),
    }


# ============================================================
# ATAJO DE COMPATIBILIDAD
# ============================================================

def build_response(
    intent_data: Dict[str, Any],
    search_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Alias compatible por si luego quieres usar otro nombre.
    """
    return generate_response(intent_data, search_payload)