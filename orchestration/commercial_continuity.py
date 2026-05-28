# ============================================================
# orchestration/commercial_continuity.py
# ============================================================
# RESPONSABILIDAD:
# Detectar continuidad comercial y capturar datos comerciales
# de forma contextual.
#
# Casos que resuelve:
# - Usuario ya seleccionó un producto.
# - Luego dice: "quiero cotizar este producto".
# - NIA debe continuar con ese producto.
# - NIA NO debe buscar productos nuevos con la frase "cotización".
# - Si NIA está esperando datos comerciales, debe interpretar
#   respuestas cortas como "Luisa", "Industrias ABC",
#   "Se llama Industrias ABC" o "luisa@abc.com" según el contexto.
#
# Alineación con Don Andrés / Commercial Spine:
# - Leer contexto antes de responder.
# - No pedir datos que ya existan en memoria.
# - Preguntar solo lo faltante.
# - Mantener producto activo.
# - Mantener estado comercial claro.
# - No inventar producto, precio, disponibilidad ni compatibilidad.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

from memory.conversation_memory import (
    get_last_selected_product,
    extract_exact_product_code,
    get_commercial_data,
    update_commercial_data,
)
from retrieval.search_adapter import search_exact_code
from services.search import formatear_producto
from orchestration.commercial_data_extractor import (
    extract_commercial_data,
    has_any_commercial_data,
    merge_commercial_data,
    get_missing_quote_fields,
    build_commercial_data_response,
)
from orchestration.commercial_state_engine import (
    update_commercial_process_state,
)


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


def _has_value(value: Any) -> bool:
    """
    Valida si un valor contiene información útil.
    """
    return value not in [None, "", [], {}]


def _title_safe(value: str) -> str:
    """
    Capitaliza de forma simple para mantener salida legible.
    """
    value = _safe_str(value)

    if not value:
        return ""

    return " ".join(part.capitalize() for part in value.split())


def _empty_commercial_data() -> Dict[str, Any]:
    """
    Estructura vacía estándar de datos comerciales.
    """
    return {
        "nombre_cliente": None,
        "empresa": None,
        "correo": None,
        "telefono": None,
        "cantidad": None,
        "presupuesto_aproximado": None,
        "fecha_estimada_compra": None,
    }


def _merge_inferred_data(base: Dict[str, Any], inferred: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combina datos inferidos sin sobrescribir datos explícitos ya detectados.
    """
    merged = dict(base or _empty_commercial_data())

    for key, value in inferred.items():
        if _has_value(value) and not _has_value(merged.get(key)):
            merged[key] = value

    return merged

# ============================================================
# SEGUIMIENTO DE COTIZACIÓN ENVIADA / RECIBIDA
# ============================================================
# Esta lista cubre frases naturales donde el cliente NO está
# pidiendo iniciar una cotización nueva, sino hablando de una
# cotización que ya fue enviada, recibida o revisada.
#
# Alineación Commercial Spine:
# - seguimiento
# - validando_cumplimiento
# - siguiente paso comercial claro
# ============================================================

QUOTE_FOLLOWUP_PHRASES = [
    # Cotización enviada
    "ya me enviaron la cotizacion",
    "ya me enviaron la cotización",
    "ya me mandaron la cotizacion",
    "ya me mandaron la cotización",
    "ya me compartieron la cotizacion",
    "ya me compartieron la cotización",
    "ya me hicieron llegar la cotizacion",
    "ya me hicieron llegar la cotización",
    "ya me pasaron la cotizacion",
    "ya me pasaron la cotización",
    "ya me enviaron el documento",
    "ya me mandaron el documento",
    "ya me compartieron el documento",

    # Cotización recibida
    "ya recibi la cotizacion",
    "ya recibí la cotización",
    "ya tengo la cotizacion",
    "ya tengo la cotización",
    "ya me llego la cotizacion",
    "ya me llegó la cotización",
    "me llego la cotizacion",
    "me llegó la cotización",
    "recibi la cotizacion",
    "recibí la cotización",
    "tengo la cotizacion",
    "tengo la cotización",
    "me enviaron la cotizacion",
    "me enviaron la cotización",
    "me mandaron la cotizacion",
    "me mandaron la cotización",

    # Referencias anafóricas: "la" = cotización en contexto
    "ya me la enviaron",
    "ya me la mandaron",
    "ya me la compartieron",
    "ya me la pasaron",
    "ya me llego",
    "ya me llegó",
    "ya la tengo",
    "ya la recibi",
    "ya la recibí",
    "me la enviaron",
    "me la mandaron",
    "me la compartieron",
    "me la pasaron",
    "me llego",
    "me llegó",

    # Revisión
    "ya revise la cotizacion",
    "ya revisé la cotización",
    "ya la revise",
    "ya la revisé",
    "estoy revisando la cotizacion",
    "estoy revisando la cotización",
    "estoy revisandola",
    "estoy revisándola",
    "la estoy revisando",
    "voy a revisar la cotizacion",
    "voy a revisar la cotización",
    "voy a revisarla",

    # Seguimiento
    "quiero revisar la cotizacion",
    "quiero revisar la cotización",
    "quiero seguir con la cotizacion",
    "quiero seguir con la cotización",
    "sigamos con la cotizacion",
    "sigamos con la cotización",
    "continuemos con la cotizacion",
    "continuemos con la cotización",
    "retomemos la cotizacion",
    "retomemos la cotización",
    "sobre la cotizacion",
    "sobre la cotización",
    "respecto a la cotizacion",
    "respecto a la cotización",

    # Estado del asesor
    "el asesor ya me envio la cotizacion",
    "el asesor ya me envió la cotización",
    "el asesor ya me la envio",
    "el asesor ya me la envió",
    "ventas ya me envio la cotizacion",
    "ventas ya me envió la cotización",
    "comercial ya me envio la cotizacion",
    "comercial ya me envió la cotización",

    # Ajustes posteriores
    "quiero ajustar la cotizacion",
    "quiero ajustar la cotización",
    "necesito ajustar la cotizacion",
    "necesito ajustar la cotización",
    "quiero modificar la cotizacion",
    "quiero modificar la cotización",
    "hay que cambiar la cotizacion",
    "hay que cambiar la cotización",
    "tengo una duda de la cotizacion",
    "tengo una duda de la cotización",
    "tengo dudas de la cotizacion",
    "tengo dudas de la cotización",
]

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

    if "cotizacion" in text:
        return True

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

def is_commercial_quote_followup_message(message: str) -> bool:
    """
    Detecta si el cliente habla de una cotización ya enviada,
    recibida, revisada o en seguimiento.

    Importante:
    Esto NO es iniciar una cotización nueva.
    Esto corresponde al estado 'seguimiento' del Commercial Spine.
    """
    text = _normalize(message)

    if not text:
        return False

    # Evita confundir solicitudes nuevas de cotización con seguimiento.
    new_quote_patterns = [
        "quiero cotizar",
        "cotizar este producto",
        "cotizar ese producto",
        "solicitar cotizacion",
        "solicitar cotización",
        "generar cotizacion",
        "generar cotización",
        "enviame una cotizacion",
        "envíame una cotización",
        "mandame una cotizacion",
        "mándame una cotización",
        "hazme una cotizacion",
        "hazme una cotización",
    ]

    if any(_normalize(pattern) in text for pattern in new_quote_patterns):
        return False

    if any(_normalize(phrase) in text for phrase in QUOTE_FOLLOWUP_PHRASES):
        return True

    # Patrones más flexibles.
    if (
        "cotizacion" in text
        and any(
            token in text
            for token in [
                "ya",
                "recibi",
                "recibida",
                "enviaron",
                "mandaron",
                "llego",
                "tengo",
                "revise",
                "revisando",
                "seguimiento",
                "ajustar",
                "modificar",
                "duda",
                "dudas",
            ]
        )
    ):
        return True

    # Frases sin la palabra cotización, pero muy claras si hay contexto.
    anaphoric_patterns = [
        "ya me la enviaron",
        "ya me la mandaron",
        "ya me llego",
        "ya me llegó",
        "ya la tengo",
        "ya la recibi",
        "ya la recibí",
        "ya la revise",
        "ya la revisé",
        "la estoy revisando",
    ]

    return any(pattern in text for pattern in anaphoric_patterns)


def build_commercial_quote_followup_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Optional[Dict[str, Any]]:
    """
    Responde cuando el cliente habla de una cotización ya enviada,
    recibida o revisada.

    Evita reiniciar la cotización y ubica el flujo en seguimiento.
    """
    if not isinstance(session, dict):
        return None

    if not is_commercial_quote_followup_message(message):
        return None

    selected_product = _normalize_selected_product_in_session(session)

    session["estado_negociacion"] = "seguimiento_cotizacion"

    update_commercial_process_state(
        session=session,
        detected_intent="seguimiento",
    )

    commercial_data = get_commercial_data(session)
    name = commercial_data.get("nombre_cliente")

    prefix = f"Perfecto, {name}." if name else "Perfecto."

    response = (
        f"{prefix} Entonces continuamos sobre la cotización enviada. "
        "¿Quieres revisarla, ajustar algún dato o avanzar con el siguiente paso comercial?"
    )

    cards = [selected_product] if selected_product and _product_code(selected_product) else []
    results = [selected_product] if selected_product and _product_code(selected_product) else []

    return {
        "intent": detected_intent,
        "response": response,
        "needs_clarification": True,
        "context": session.get("context", {}),
        "session_id": session.get("session_id"),
        "decision_reason": "commercial_quote_followup",
        "compatible_count": len(results),
        "requires_customer_data": False,

        "commercial_data": commercial_data,

        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes": session.get("datos_faltantes"),
        "intencion_actual": session.get("intencion_actual"),

        "cards": cards,
        "results": results,
    }

# ============================================================
# RECUPERACIÓN / NORMALIZACIÓN DE PRODUCTO
# ============================================================

def _format_selected_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza el producto seleccionado usando el formateador oficial,
    pero sin perder campos si el producto ya viene normalizado.

    Evita que una card quede vacía durante continuidad comercial.
    """
    if not isinstance(product, dict):
        return {}

    original = dict(product)

    try:
        formatted = formatear_producto(product)

        if isinstance(formatted, dict) and formatted:
            merged = dict(formatted)

            critical_fields = [
                "codigo",
                "referencia",
                "ref_alternativa",
                "nombre",
                "descripcion",
                "marca",
                "precio",
                "disponibilidad",
                "tiempo_entrega",
                "nivel_0",
                "nivel_1",
                "nivel_2",
                "nivel_3",
                "nivel_4",
                "caracteristicas",
                "aplicaciones",
                "dimension",
                "peso",
                "equivalente",
                "equivalente_2",
                "score_oportunidad",
                "tipo_sku",
            ]

            for field in critical_fields:
                if not _has_value(merged.get(field)) and _has_value(original.get(field)):
                    merged[field] = original.get(field)

            if not _has_value(merged.get("codigo")):
                merged["codigo"] = (
                    original.get("CODIGO")
                    or original.get("codigo")
                    or ""
                )

            if not _has_value(merged.get("referencia")):
                merged["referencia"] = (
                    original.get("REFERENCIA")
                    or original.get("referencia")
                    or ""
                )

            if not _has_value(merged.get("ref_alternativa")):
                merged["ref_alternativa"] = (
                    original.get("REF_ALTERNATIVA")
                    or original.get("ref_alternativa")
                    or ""
                )

            if not _has_value(merged.get("nombre")):
                merged["nombre"] = (
                    original.get("DESCRIPCION_CORTA_PRE")
                    or original.get("NOMBRE")
                    or original.get("descripcion")
                    or original.get("nombre")
                    or ""
                )

            if not _has_value(merged.get("descripcion")):
                merged["descripcion"] = (
                    original.get("DESCRIPCION")
                    or original.get("descripcion")
                    or original.get("nombre")
                    or ""
                )

            if not _has_value(merged.get("marca")):
                merged["marca"] = (
                    original.get("MARCA_LET")
                    or original.get("MARCA")
                    or original.get("marca")
                    or ""
                )

            if not _has_value(merged.get("precio")):
                merged["precio"] = (
                    original.get("PRECIO")
                    or original.get("precio_formateado")
                    or original.get("precio")
                    or "Consultarnos"
                )

            if not _has_value(merged.get("disponibilidad")):
                merged["disponibilidad"] = (
                    original.get("DISPONIBILIDAD")
                    or original.get("stock")
                    or original.get("STOCK")
                    or original.get("disponibilidad")
                    or "Consultar disponibilidad"
                )

            if not _has_value(merged.get("tiempo_entrega")):
                merged["tiempo_entrega"] = (
                    original.get("TIEMPO_ENTREGA")
                    or original.get("entrega")
                    or original.get("tiempo_entrega")
                    or ""
                )

            if not isinstance(merged.get("caracteristicas"), list):
                merged["caracteristicas"] = original.get("caracteristicas", [])

            return merged

    except Exception:
        pass

    return original


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
    if not isinstance(session, dict):
        return None

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
    Recupera producto desde código guardado en contexto o memoria.
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
# RESPUESTA DE INICIO DE COTIZACIÓN
# ============================================================

def build_commercial_continuity_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Optional[Dict[str, Any]]:
    """
    Si el mensaje es continuidad comercial y hay producto seleccionado,
    construye respuesta sin buscar productos nuevos.

    Además conecta el estado interno de NIA con el Commercial Spine:
    cotizacion_en_proceso -> preparar_cotizacion.
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

    if not codigo:
        recovered_product = _recover_product_from_context_code(session)

        if recovered_product:
            selected_product = _format_selected_product(recovered_product)
            codigo = _product_code(selected_product)

    if not codigo:
        return None

    session["last_selected_product"] = selected_product
    session["last_selected_product_code"] = codigo
    session["estado_negociacion"] = "cotizacion_en_proceso"

    update_commercial_process_state(
        session=session,
        detected_intent=detected_intent,
    )

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

        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes": session.get("datos_faltantes"),
        "intencion_actual": session.get("intencion_actual"),

        "cards": [selected_product],
        "results": [selected_product],
    }


# ============================================================
# CAPTURA CONTEXTUAL DE DATOS COMERCIALES
# ============================================================

def _is_waiting_for_commercial_customer_data(session: Dict[str, Any]) -> bool:
    """
    Detecta si NIA está esperando datos comerciales del cliente.

    No dependemos únicamente de estado_negociacion porque en producción
    puede haber cambios de worker, sesión rehidratada o estados anteriores.

    Señales válidas:
    - estado comercial de cotización
    - último mensaje de NIA pidió datos de contacto
    - historial reciente contiene la solicitud de datos
    - existe producto activo seleccionado y estado comercial
    """
    if not isinstance(session, dict):
        return False

    estado_negociacion = session.get("estado_negociacion")

    estados_validos = {
        "cotizacion_en_proceso",
        "cotizacion_pendiente",
        "datos_cotizacion_parciales",
    }

    if estado_negociacion in estados_validos:
        return True

    last_question = _normalize(
        session.get("last_assistant_question_text")
        or session.get("last_assistant_question")
        or ""
    )

    if (
        "cotizacion" in last_question
        and (
            "nombre" in last_question
            or "empresa" in last_question
            or "correo" in last_question
            or "telefono" in last_question
        )
    ):
        return True

    history = session.get("history", [])

    if isinstance(history, list) and history:
        last_assistant_messages = [
            item.get("content", "")
            for item in history[-5:]
            if isinstance(item, dict) and item.get("role") == "assistant"
        ]

        joined = _normalize(" ".join(last_assistant_messages))

        if (
            "cotizacion" in joined
            and (
                "nombre" in joined
                or "empresa" in joined
                or "correo" in joined
                or "telefono" in joined
            )
        ):
            return True


    return False


def _get_current_missing_quote_fields(session: Dict[str, Any]) -> List[str]:
    """
    Calcula datos faltantes actuales usando commercial_data de sesión.
    """
    current_data = get_commercial_data(session)
    return get_missing_quote_fields(current_data)


def _message_has_product_or_search_intent(message: str) -> bool:
    """
    Evita interpretar como nombre/empresa mensajes que parecen búsqueda de producto.
    """
    text = _normalize(message)

    product_words = {
        "sensor",
        "sensores",
        "motor",
        "motores",
        "variador",
        "variadores",
        "plc",
        "rele",
        "relé",
        "valvula",
        "válvula",
        "torquimetro",
        "torquímetro",
        "precio",
        "producto",
        "cotizacion",
        "cotización",
        "referencia",
        "codigo",
        "código",
        "marca",
        "siemens",
        "lutron",
        "autonics",
        "weg",
        "schneider",
        "abb",
        "omron",
        "delta",
    }

    return any(word in text.split() or word in text for word in product_words)


def _is_meta_commercial_reply(message: str) -> bool:
    """
    Detecta mensajes donde el usuario se queja/corrige,
    pero no entrega el dato exacto.

    Estos mensajes NO deben caer a búsqueda de productos.
    """
    text = _normalize(message)

    meta_patterns = [
        "te estoy dando mi nombre",
        "te di mi nombre",
        "ya te dije mi nombre",
        "ya te di mi nombre",
        "ese es mi nombre",
        "es mi nombre",
        "te estoy dando la empresa",
        "te di la empresa",
        "ya te dije la empresa",
        "ya te di la empresa",
        "esa es la empresa",
        "es la empresa",
        "te estoy dando el correo",
        "te di el correo",
        "ya te dije el correo",
        "ya te di el correo",
        "ese es mi correo",
        "te estoy dando mi telefono",
        "te di mi telefono",
        "ya te dije mi telefono",
        "ya te di mi telefono",
        "ese es mi telefono",
        "ya te lo dije",
        "ya te lo di",
        "ya lo dije",
        "ya lo di",
        "te lo acabo de decir",
        "ya te pase eso",
        "ya te pasé eso",
    ]

    return any(pattern in text for pattern in meta_patterns)


def _clean_short_value(message: str) -> str:
    """
    Limpia respuestas cortas tipo:
    - "Luisa"
    - "Industrias ABC"
    - "Se llama Industrias ABC"
    - "Es Industrias ABC"
    """
    raw = _safe_str(message)

    raw = re.sub(
        r"^(?:se llama|es|la llaman|se denomina|nombre|empresa)\s*[:\-]?\s+",
        "",
        raw,
        flags=re.IGNORECASE,
    )

    raw = re.sub(
        r"^(?:mi nombre es|me llamo|soy|mi empresa es|la empresa es|la empresa se llama)\s+",
        "",
        raw,
        flags=re.IGNORECASE,
    )

    raw = re.split(
        r"\s+(?:mi correo|correo|email|e-mail|telefono|teléfono|celular|mi numero|mi número)\b",
        raw,
        flags=re.IGNORECASE,
    )[0]

    return _safe_str(raw.strip(" .,:;|-"))


def _looks_like_person_name_short_answer(message: str) -> bool:
    """
    Decide si un mensaje corto puede ser nombre de persona.

    Solo se usa cuando NIA ya está esperando datos comerciales.

    Importante:
    No debe confundir nombres como "Luisa" con empresa solo porque
    contienen letras como "sa".
    """
    value = _clean_short_value(message)
    text = _normalize(value)

    if not value or not text:
        return False

    if _is_meta_commercial_reply(message):
        return False

    if _message_has_product_or_search_intent(message):
        return False

    if re.search(r"\d", value):
        return False

    words = value.split()

    if not (1 <= len(words) <= 5):
        return False

    blocked = {
        "si",
        "sí",
        "no",
        "ok",
        "listo",
        "dale",
        "gracias",
        "empresa",
        "correo",
        "telefono",
        "teléfono",
        "cotizacion",
        "cotización",
    }

    if text in blocked:
        return False

    # Marcadores empresariales largos.
    # Estos sí pueden aparecer dentro de una razón social.
    long_company_markers = {
        "industria",
        "industrias",
        "industrial",
        "constructora",
        "ferreteria",
        "ferretería",
        "comercializadora",
        "distribuciones",
        "servicios",
        "soluciones",
        "ingenieria",
        "ingeniería",
        "taller",
        "corporacion",
        "corporación",
        "grupo",
        "compañia",
        "compania",
        "company",
    }

    if any(marker in text for marker in long_company_markers):
        return False

    # Marcadores empresariales cortos.
    # Deben validarse como palabra completa, no como substring.
    # Ejemplo:
    # - "ABC SA" sí es empresa.
    # - "Luisa" NO debe fallar por contener "sa".
    short_company_markers = {
        "sa",
        "s.a",
        "sas",
        "s.a.s",
        "ltda",
        "limitada",
    }

    text_tokens = set(text.replace(".", " ").split())

    if text in short_company_markers:
        return False

    if any(marker in text_tokens for marker in short_company_markers):
        return False

    return bool(re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,80}", value))


def _looks_like_company_short_answer(message: str) -> bool:
    """
    Decide si un mensaje corto puede ser empresa.

    Solo se usa cuando NIA ya está esperando empresa.

    Regla importante:
    Una sola palabra como "Luisa", "Carlos" o "Andrea" NO debe
    considerarse empresa.

    Además, dos palabras tipo "Luis Diaz" tampoco deben considerarse
    empresa si no tienen señales empresariales claras.
    """
    value = _clean_short_value(message)
    text = _normalize(value)

    if not value or not text:
        return False

    if _is_meta_commercial_reply(message):
        return False

    if _message_has_product_or_search_intent(message):
        return False

    words = value.split()

    if not (1 <= len(words) <= 8):
        return False

    if re.search(r"@", value):
        return False

    if re.fullmatch(r"\+?\d[\d\s().-]{6,}\d", value):
        return False

    # Una sola palabra no se considera empresa.
    if len(words) == 1:
        return False

    long_company_markers = [
        "industria",
        "industrias",
        "industrial",
        "constructora",
        "ferreteria",
        "ferretería",
        "comercializadora",
        "distribuciones",
        "distribuidora",
        "servicios",
        "soluciones",
        "ingenieria",
        "ingeniería",
        "taller",
        "corporacion",
        "corporación",
        "grupo",
        "compañia",
        "compania",
        "company",
        "empresa",
    ]

    if any(marker in text for marker in long_company_markers):
        return True

    # Marcadores legales: deben ser palabra completa.
    short_company_markers = {
        "sa",
        "sas",
        "ltda",
        "limitada",
    }

    normalized_tokens = set(
        token.strip(".").lower()
        for token in re.split(r"\s+", value)
        if token.strip()
    )

    dotted_legal_markers = {
        "s.a",
        "s.a.",
        "s.a.s",
        "s.a.s.",
    }

    if any(marker in normalized_tokens for marker in short_company_markers):
        return True

    if any(marker in text for marker in dotted_legal_markers):
        return True

    # Acrónimo empresarial en mayúsculas.
    # Ejemplos:
    # - ABC
    # - VIA
    # - XYZ
    #
    # Esto permite "ABC Industrial" o "Servicios ABC".
    uppercase_tokens = [
        token.strip(".,;:-")
        for token in value.split()
        if token.strip(".,;:-").isupper()
        and len(token.strip(".,;:-")) >= 2
    ]

    if uppercase_tokens:
        return True

    # Si no hay ninguna señal empresarial clara, no inferimos empresa.
    # Preferimos pedir aclaración antes que inventar.
    return False


def _extract_contact_from_short_answer(message: str) -> Dict[str, Any]:
    """
    Extrae correo o teléfono desde respuesta corta.
    Reutiliza el extractor principal para no duplicar reglas.
    """
    data = extract_commercial_data(message)

    return {
        "correo": data.get("correo"),
        "telefono": data.get("telefono"),
    }


def _infer_commercial_data_from_context(
    session: Dict[str, Any],
    message: str,
    incoming_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Inferencia contextual de datos comerciales.

    Esta función es la capa clave de conversación natural.

    Regla principal:
    - Si falta nombre y el mensaje parece nombre corto, NOMBRE manda por encima
      de cualquier dato ambiguo detectado por el extractor.
    - Si ya hay nombre y falta empresa, una respuesta corta tipo
      "Industrias ABC" se interpreta como empresa.
    - Si viene correo o teléfono, se conserva como contacto.
    """
    inferred = dict(incoming_data or _empty_commercial_data())

    current_data = get_commercial_data(session)
    missing = get_missing_quote_fields(current_data)

    if not missing:
        return inferred

    clean_value = _clean_short_value(message)
    normalized = _normalize(message)

    # --------------------------------------------------------
    # 1. Contacto explícito: correo/teléfono siempre se respeta.
    # --------------------------------------------------------
    contact_data = _extract_contact_from_short_answer(message)

    if "correo o teléfono" in missing:
        if _has_value(contact_data.get("correo")):
            inferred["correo"] = contact_data["correo"]

        if _has_value(contact_data.get("telefono")):
            inferred["telefono"] = contact_data["telefono"]

    # Si el mensaje trajo contacto explícito, retornamos.
    # Ejemplo:
    # - "luisa@abc.com"
    # - "3001234567"
    if _has_value(inferred.get("correo")) or _has_value(inferred.get("telefono")):
        return inferred

    # --------------------------------------------------------
    # 2. Mensajes meta/corrección.
    # No deben llenar datos ni caer al buscador.
    # Otra función hará la aclaración.
    # --------------------------------------------------------
    if _is_meta_commercial_reply(message):
        return _empty_commercial_data()

    # --------------------------------------------------------
    # 3. PRIORIDAD MÁXIMA: si falta nombre y el mensaje parece
    # nombre corto, se guarda como nombre aunque el extractor
    # lo haya clasificado como empresa.
    #
    # Este bloque corrige:
    # "Luisa" -> nombre_cliente = "Luisa"
    # NO empresa = "Luisa"
    # --------------------------------------------------------
    if "nombre" in missing and _looks_like_person_name_short_answer(message):
        return {
            "nombre_cliente": _title_safe(clean_value),
            "empresa": None,
            "correo": None,
            "telefono": None,
            "cantidad": None,
            "presupuesto_aproximado": None,
            "fecha_estimada_compra": None,
        }

    # --------------------------------------------------------
    # 4. Mensajes con marcador "se llama / es / se denomina".
    # Se interpretan según el slot faltante.
    # --------------------------------------------------------
    has_name_marker = (
        normalized.startswith("se llama")
        or normalized.startswith("es ")
        or normalized.startswith("la llaman")
        or normalized.startswith("se denomina")
    )

    if has_name_marker:
        if "empresa" in missing and _looks_like_company_short_answer(message):
            return {
                "nombre_cliente": None,
                "empresa": _title_safe(clean_value),
                "correo": None,
                "telefono": None,
                "cantidad": None,
                "presupuesto_aproximado": None,
                "fecha_estimada_compra": None,
            }

        if "nombre" in missing and _looks_like_person_name_short_answer(message):
            return {
                "nombre_cliente": _title_safe(clean_value),
                "empresa": None,
                "correo": None,
                "telefono": None,
                "cantidad": None,
                "presupuesto_aproximado": None,
                "fecha_estimada_compra": None,
            }

    # --------------------------------------------------------
    # 5. Si falta empresa y el mensaje parece empresa corta,
    # se guarda como empresa.
    #
    # Esto ocurre normalmente después de que ya tenemos nombre:
    # "Industrias ABC" -> empresa
    # --------------------------------------------------------
    if "empresa" in missing and _looks_like_company_short_answer(message):
        return {
            "nombre_cliente": None,
            "empresa": _title_safe(clean_value),
            "correo": None,
            "telefono": None,
            "cantidad": None,
            "presupuesto_aproximado": None,
            "fecha_estimada_compra": None,
        }

    # --------------------------------------------------------
    # 6. Si no se pudo inferir de forma segura, devolvemos los
    # datos originales del extractor. Esto permite conservar
    # casos explícitos como:
    # - "Me llamo Carlos"
    # - "Mi empresa es Industrias ABC"
    # --------------------------------------------------------
    return inferred


def _focus_missing_field_from_message_or_session(
    session: Dict[str, Any],
    message: str,
) -> str:
    """
    Decide qué dato debe aclarar NIA cuando el usuario responde de forma meta
    o ambigua.
    """
    text = _normalize(message)
    current_data = get_commercial_data(session)
    missing = get_missing_quote_fields(current_data)

    if "nombre" in text:
        return "nombre"

    if "empresa" in text or "compania" in text or "compañia" in text:
        return "empresa"

    if "correo" in text or "email" in text or "mail" in text:
        return "correo o teléfono"

    if "telefono" in text or "teléfono" in text or "celular" in text or "numero" in text or "número" in text:
        return "correo o teléfono"

    if "nombre" in missing:
        return "nombre"

    if "empresa" in missing:
        return "empresa"

    if "correo o teléfono" in missing:
        return "correo o teléfono"

    return ""


def _build_contextual_clarification_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Dict[str, Any]:
    """
    Respuesta segura cuando NIA está esperando datos comerciales,
    pero el mensaje no trae un dato claro.

    Importante:
    No deja caer el mensaje a búsqueda de productos.
    """
    current_data = get_commercial_data(session)
    missing = get_missing_quote_fields(current_data)
    focus = _focus_missing_field_from_message_or_session(session, message)

    if missing:
        session["estado_negociacion"] = "datos_cotizacion_parciales"

    update_commercial_process_state(
        session=session,
        detected_intent=detected_intent,
    )

    name = current_data.get("nombre_cliente")
    prefix = f"Entiendo, {name}." if name else "Entiendo."

    if focus == "nombre":
        response = (
            f"{prefix} Para evitar confusión, "
            "¿me confirmas tu nombre exactamente?"
        )
    elif focus == "empresa":
        response = (
            f"{prefix} ¿Me confirmas el nombre de la empresa?"
        )
    elif focus == "correo o teléfono":
        response = (
            f"{prefix} ¿Me confirmas un correo o teléfono de contacto?"
        )
    else:
        response = (
            f"{prefix} Para continuar con la cotización, "
            "¿me confirmas nombre, empresa y correo o teléfono?"
        )

    selected_product = get_last_selected_product(session)

    if selected_product:
        selected_product = _format_selected_product(selected_product)

    cards = [selected_product] if selected_product and _product_code(selected_product) else []
    results = [selected_product] if selected_product and _product_code(selected_product) else []

    return {
        "intent": detected_intent,
        "response": response,
        "needs_clarification": True,
        "context": session.get("context", {}),
        "session_id": session.get("session_id"),
        "decision_reason": "commercial_contextual_clarification",
        "compatible_count": len(results),
        "requires_customer_data": True,

        "commercial_data": current_data,

        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes": session.get("datos_faltantes"),
        "intencion_actual": session.get("intencion_actual"),

        "cards": cards,
        "results": results,
    }


def _normalize_selected_product_in_session(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normaliza y conserva el producto activo dentro de la sesión.
    """
    selected_product = get_last_selected_product(session)

    if selected_product:
        selected_product = _format_selected_product(selected_product)
        selected_code = _product_code(selected_product)

        if not selected_code:
            recovered_product = _recover_product_from_context_code(session)

            if recovered_product:
                selected_product = _format_selected_product(recovered_product)
                selected_code = _product_code(selected_product)

        if selected_code:
            session["last_selected_product"] = selected_product
            session["last_selected_product_code"] = selected_code
            return selected_product

    recovered_product = _recover_product_from_context_code(session)

    if recovered_product:
        selected_product = _format_selected_product(recovered_product)
        selected_code = _product_code(selected_product)

        if selected_code:
            session["last_selected_product"] = selected_product
            session["last_selected_product_code"] = selected_code
            return selected_product

    return None


def build_commercial_data_capture_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Optional[Dict[str, Any]]:
    """
    Captura datos comerciales cuando ya hay una cotización en proceso.

    Cambio clave:
    Antes, si extract_commercial_data() no encontraba datos explícitos,
    el flujo retornaba None y el mensaje caía al buscador.

    Ahora:
    - Primero verificamos si NIA está esperando datos comerciales.
    - Luego extraemos datos explícitos.
    - Si no hay datos explícitos, inferimos por contexto.
    - Si sigue ambiguo, respondemos pidiendo el dato faltante.
    - Nunca dejamos caer respuestas comerciales cortas a búsqueda de producto.
    """
    if not isinstance(session, dict):
        return None

    incoming_data = extract_commercial_data(message)
    
    # --------------------------------------------------------
    # Si el cliente habla de una cotización ya enviada/recibida,
    # este mensaje debe pasar al bloque de seguimiento.
    # No debe tratarse como captura de datos ni como inicio
    # de cotización nueva.
    # --------------------------------------------------------
    if is_commercial_quote_followup_message(message):
        return None

    # --------------------------------------------------------
    # Si el usuario está pidiendo cotización del producto activo,
    # este mensaje debe pasar a build_commercial_continuity_response().
    #
    # No debe ser tratado como captura de datos comerciales.
    # --------------------------------------------------------
    if (
        is_commercial_continuation_message(message)
        and not has_any_commercial_data(incoming_data)
    ):
        return None

    # Primero validamos contexto comercial real.
    # Solo capturamos respuestas cortas si NIA ya inició cotización
    # o está esperando datos faltantes.
    if not _is_waiting_for_commercial_customer_data(session):
        return None

    # Si el usuario está en flujo comercial y responde algo meta,
    # no lo mandamos al buscador.
    if not has_any_commercial_data(incoming_data) and _is_meta_commercial_reply(message):
        return _build_contextual_clarification_response(
            session=session,
            message=message,
            detected_intent=detected_intent,
        )

    # Inferencia contextual para respuestas cortas:
    # "Luisa", "Industrias ABC", "Se llama Industrias ABC", etc.
    incoming_data = _infer_commercial_data_from_context(
        session=session,
        message=message,
        incoming_data=incoming_data,
    )

    # Si aun así no tenemos datos, respondemos dentro del flujo comercial.
    # No dejamos que vaya al buscador.
    if not has_any_commercial_data(incoming_data):
        return _build_contextual_clarification_response(
            session=session,
            message=message,
            detected_intent=detected_intent,
        )

    current_data = get_commercial_data(session)
    merged_data = merge_commercial_data(current_data, incoming_data)

    update_commercial_data(session, merged_data)

    missing = get_missing_quote_fields(merged_data)

    if missing:
        session["estado_negociacion"] = "datos_cotizacion_parciales"
    else:
        session["estado_negociacion"] = "datos_cotizacion_recibidos"

    selected_product = _normalize_selected_product_in_session(session)

    update_commercial_process_state(
        session=session,
        detected_intent=detected_intent,
    )

    response_text = build_commercial_data_response(merged_data)

    cards = [selected_product] if selected_product and _product_code(selected_product) else []
    results = [selected_product] if selected_product and _product_code(selected_product) else []

    return {
        "intent": detected_intent,
        "response": response_text,
        "needs_clarification": bool(missing),
        "context": session.get("context", {}),
        "session_id": session.get("session_id"),
        "decision_reason": "commercial_data_capture",
        "compatible_count": len(results),
        "requires_customer_data": bool(missing),

        "commercial_data": merged_data,

        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes": session.get("datos_faltantes"),
        "intencion_actual": session.get("intencion_actual"),

        "cards": cards,
        "results": results,
    }