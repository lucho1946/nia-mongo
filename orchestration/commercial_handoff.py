# ============================================================
# orchestration/commercial_handoff.py
# ============================================================
# RESPONSABILIDAD:
# Construir una oportunidad comercial estructurada cuando NIA
# llegue a un punto accionable para asesor:
#
# - cotizacion_lista_para_asesor
# - proforma_lista_para_asesor
#
# Este módulo NO envía correos.
# Este módulo NO crea CRM todavía.
# Este módulo NO modifica catálogo.
#
# Por ahora deja guardado el objeto en:
# session["commercial_handoff"]
#
# Luego este objeto puede conectarse con:
# - Bitrix
# - CRM
# - panel de asesor
# - webhook interno
# - almacenamiento MongoDB dedicado
#
# Alineación con Don Andrés:
# NIA no solo conversa; debe dejar una oportunidad comercial
# clara, ordenada y accionable.
# ============================================================

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ============================================================
# UTILIDADES
# ============================================================

def _safe_str(value: Any) -> Optional[str]:
    """
    Convierte valores a string limpio.

    Retorna None si el valor está vacío.
    """
    if value in [None, "", [], {}]:
        return None

    text = str(value).strip()

    return text if text else None

def _split_availability_and_delivery(
    availability: Optional[str],
    delivery_time: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Separa disponibilidad y tiempo de entrega cuando vienen unidos.

    Ejemplo:
    "Disponible en Bogotá (6 und) · 1 DIAS"
    se convierte en:
    disponibilidad = "Disponible en Bogotá (6 und)"
    tiempo_entrega = "1 DIAS"

    Esto evita que el handoff mezcle ambos datos.
    """
    clean_availability = _safe_str(availability)
    clean_delivery_time = _safe_str(delivery_time)

    if not clean_availability:
        return clean_availability, clean_delivery_time

    # Caso1 común generado por response_engine:
    # "Disponible en Bogotá (6 und) · 1 DIAS"
    if "·" in clean_availability:
        parts = [
            part.strip()
            for part in clean_availability.split("·", 1)
            if part.strip()
        ]

        if parts:
            clean_availability = parts[0]

        if len(parts) > 1 and not clean_delivery_time:
            clean_delivery_time = parts[1]

    return clean_availability, clean_delivery_time

def _get_commercial_data(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene los datos comerciales de la sesión de forma segura.
    """
    data = session.get("commercial_data")

    if isinstance(data, dict):
        return data

    return {}


def _get_active_product(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene el producto activo desde la sesión.

    Prioridad:
    1. last_selected_product_card:
       card limpia generada por response_engine, conserva precio/disponibilidad.
    2. last_selected_product:
       producto activo estándar.
    3. primer elemento de last_results:
       respaldo por si el producto activo fue reducido.
    4. last_selected_product_code:
       último recurso, solo código.
    """
    product_card = session.get("last_selected_product_card")

    if isinstance(product_card, dict) and product_card.get("codigo"):
        return product_card

    product = session.get("last_selected_product")

    if isinstance(product, dict) and product.get("codigo"):
        return product

    last_results = session.get("last_results")

    if isinstance(last_results, list) and last_results:
        first_result = last_results[0]

        if isinstance(first_result, dict):
            return first_result

    product_code = session.get("last_selected_product_code")

    if product_code:
        return {
            "codigo": product_code,
        }

    return {}


def _now_iso() -> str:
    """
    Fecha/hora UTC para trazabilidad.
    """
    return datetime.now(timezone.utc).isoformat()


def _detect_handoff_type(session: Dict[str, Any]) -> Optional[str]:
    """
    Detecta si el handoff corresponde a cotización o proforma.
    """
    estado = _safe_str(session.get("estado_negociacion"))
    process_state = _safe_str(session.get("commercial_process_state"))

    if estado in {
        "datos_proforma_recibidos",
        "proforma_lista_para_asesor",
    }:
        return "proforma"

    if process_state == "proforma_lista_para_asesor":
        return "proforma"

    if estado in {
        "datos_cotizacion_recibidos",
        "datos_cotizacion_completos",
        "cotizacion_lista_para_asesor",
    }:
        return "cotizacion"

    if process_state == "cotizacion_lista_para_asesor":
        return "cotizacion"

    return None


def should_build_commercial_handoff(session: Dict[str, Any]) -> bool:
    """
    Indica si la sesión ya llegó a un punto donde debe crearse
    una oportunidad comercial para asesor.
    """
    return _detect_handoff_type(session) is not None


# ============================================================
# CONSTRUCCIÓN DEL HANDOFF
# ============================================================

def build_commercial_handoff(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Construye el objeto de oportunidad comercial.

    No guarda por sí solo.
    Solo retorna el objeto.
    """
    if not isinstance(session, dict):
        return None

    handoff_type = _detect_handoff_type(session)

    if not handoff_type:
        return None

    commercial_data = _get_commercial_data(session)
    product = _get_active_product(session)
    
    previous_handoff = session.get("commercial_handoff")

    if not isinstance(previous_handoff, dict):
        previous_handoff = {}

    product_code = (
        _safe_str(product.get("codigo"))
        or _safe_str(session.get("last_selected_product_code"))
    )

    product_name = (
        _safe_str(product.get("nombre"))
        or _safe_str(product.get("name"))
        or _safe_str(product.get("NOMBRE_PRODUCTO"))
        or _safe_str(previous_handoff.get("producto_nombre"))
    )

    product_brand = (
        _safe_str(product.get("marca"))
        or _safe_str(product.get("brand"))
        or _safe_str(product.get("MARCA_LET"))
        or _safe_str(previous_handoff.get("producto_marca"))
    )

    product_reference = (
        _safe_str(product.get("referencia"))
        or _safe_str(product.get("ref"))
        or _safe_str(product.get("REFERENCIA"))
        or _safe_str(previous_handoff.get("producto_referencia"))
    )

    raw_product_price = (
        _safe_str(product.get("precio"))
        or _safe_str(product.get("precio_formateado"))
        or _safe_str(product.get("price"))
        or _safe_str(product.get("PRECIO"))
        or _safe_str(product.get("PV_PRECIO"))
        or _safe_str(product.get("PV"))
    )

    raw_product_availability = (
        _safe_str(product.get("disponibilidad"))
        or _safe_str(product.get("availability"))
        or _safe_str(product.get("DISPONIBILIDAD"))
        or _safe_str(product.get("stock_text"))
    )

    raw_delivery_time = (
        _safe_str(product.get("tiempo_entrega"))
        or _safe_str(product.get("entrega"))
        or _safe_str(product.get("EXISTENCIA"))
    )

    # ------------------------------------------------------------
    # Preservación de datos comerciales del producto.
    #
    # Durante el flujo, algunas cards pueden llegar con valores
    # genéricos como "Consultarnos" o "Consultar disponibilidad".
    # Si ya teníamos un handoff anterior con mejor precio o stock,
    # lo reutilizamos para no degradar la oportunidad comercial.
    # ------------------------------------------------------------
    product_price = raw_product_price

    if product_price in [None, "Consultarnos", "Consultar", ""]:
        product_price = _safe_str(previous_handoff.get("producto_precio"))

    product_availability = raw_product_availability

    if product_availability in [None, "Consultar disponibilidad", "Consultar", ""]:
        product_availability = _safe_str(
            previous_handoff.get("producto_disponibilidad")
        )

    delivery_time = raw_delivery_time

    if delivery_time in [None, ""]:
        delivery_time = _safe_str(
            previous_handoff.get("producto_tiempo_entrega")
        )
    # ------------------------------------------------------------
    # Normalizar disponibilidad y tiempo de entrega.
    #
    # Algunas cards llegan con ambos datos juntos:
    # "Disponible en Bogotá (6 und) · 1 DIAS"
    #
    # Para el handoff los guardamos separados:
    # - producto_disponibilidad
    # - producto_tiempo_entrega
    # ------------------------------------------------------------
    product_availability, delivery_time = _split_availability_and_delivery(
        availability=product_availability,
        delivery_time=delivery_time,
    )

    documento_fiscal = (
        _safe_str(commercial_data.get("documento_fiscal"))
        or _safe_str(commercial_data.get("nit"))
        or _safe_str(commercial_data.get("rut"))
        or _safe_str(commercial_data.get("documento"))
    )

    contact_phone = (
        _safe_str(commercial_data.get("telefono"))
        or _safe_str(session.get("channel_contact_phone"))
    )

    contact_source = (
        _safe_str(session.get("commercial_contact_source"))
        or ("channel_phone" if session.get("channel_contact_phone") else None)
        or "manual"
    )

    if handoff_type == "proforma":
        estado = "lista_para_asesor"
        siguiente_paso = "revision_asesor"
    else:
        estado = "lista_para_asesor"
        siguiente_paso = "generar_o_enviar_cotizacion"

    handoff = {
        "handoff_id": f"{handoff_type}_{_safe_str(session.get('session_id')) or 'sin_session'}",
        "tipo": handoff_type,
        "estado": estado,
        "siguiente_paso": siguiente_paso,
        "created_at": _now_iso(),

        # Sesión / canal
        "session_id": _safe_str(session.get("session_id")),
        "canal": _safe_str(session.get("canal")),
        "cliente_id": _safe_str(session.get("cliente_id")),
        "contact_source": contact_source,

        # Producto
        "producto_codigo": product_code,
        "producto_nombre": product_name,
        "producto_marca": product_brand,
        "producto_referencia": product_reference,
        "producto_precio": product_price,
        "producto_disponibilidad": product_availability,
        "producto_tiempo_entrega": delivery_time,

        # Cliente / contacto
        "cliente": _safe_str(commercial_data.get("nombre_cliente")),
        "empresa": _safe_str(commercial_data.get("empresa")),
        "correo": _safe_str(commercial_data.get("correo")),
        "telefono": contact_phone,

        # Documento fiscal
        "documento_fiscal": documento_fiscal,
        "nit": _safe_str(commercial_data.get("nit")),
        "rut": _safe_str(commercial_data.get("rut")),

        # Extras comerciales
        "cantidad": _safe_str(commercial_data.get("cantidad")),
        "presupuesto_aproximado": _safe_str(
            commercial_data.get("presupuesto_aproximado")
        ),
        "fecha_estimada_compra": _safe_str(
            commercial_data.get("fecha_estimada_compra")
        ),

        # Estado NIA
        "estado_negociacion": _safe_str(session.get("estado_negociacion")),
        "commercial_process_id": _safe_str(session.get("commercial_process_id")),
        "commercial_process_state": _safe_str(
            session.get("commercial_process_state")
        ),
        "ultimo_paso": _safe_str(session.get("ultimo_paso")),
    }

    return handoff


def attach_commercial_handoff(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Construye y guarda el handoff en la sesión.

    Retorna el handoff si se creó.
    Retorna None si la sesión aún no está lista.
    """
    handoff = build_commercial_handoff(session)

    if not handoff:
        return None

    session["commercial_handoff"] = handoff

    return handoff