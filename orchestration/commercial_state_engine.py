# ============================================================
# orchestration/commercial_state_engine.py
# ============================================================
# RESPONSABILIDAD:
# Traducir los estados comerciales actuales de NIA hacia los
# estados oficiales definidos en:
#
# knowledge/nia_os/processes/process_commercial_spine_v1.json
#
# Este módulo es un puente entre:
# - conversation_memory.py
# - commercial_continuity.py
# - commercial_data_extractor.py
# - process_commercial_spine_v1.json
#
# IMPORTANTE:
# Esta primera versión NO ejecuta los 19 estados completos.
# Solo conecta los estados actuales ya probados:
#
# producto_seleccionado      -> producto_identificado
# cotizacion_en_proceso      -> preparar_cotizacion
# datos_cotizacion_parciales -> pedir_datos_faltantes_cotizacion
# datos_cotizacion_recibidos -> cotizacion_lista_para_asesor
#
# Alineación con Don Andrés:
# - Leer memoria antes de responder.
# - No pedir datos repetidos.
# - Calcular faltantes.
# - Mantener estado comercial claro.
# - Dejar siguiente paso comercial definido.
# ============================================================

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from knowledge.nia_os_loader import get_commercial_spine_process


# ============================================================
# CONSTANTES
# ============================================================

COMMERCIAL_SPINE_ID = "process_commercial_spine_v1"


# Estados internos actuales de NIA -> Estados oficiales del Spine.
INTERNAL_TO_SPINE_STATE = {
    "producto_seleccionado": "producto_identificado",
    "producto_identificado": "producto_identificado",

    "cotizacion_en_proceso": "preparar_cotizacion",
    "cotizacion_pendiente": "preparar_cotizacion",

    "datos_cotizacion_parciales": "pedir_datos_faltantes_cotizacion",
    "datos_cotizacion_recibidos": "cotizacion_lista_para_asesor",
    "datos_cotizacion_completos": "cotizacion_lista_para_asesor",
}


# Siguiente paso sugerido para cada estado del Spine.
SPINE_NEXT_STEP = {
    "producto_identificado": "preparar_cotizacion",
    "preparar_cotizacion": "pedir_datos_faltantes_cotizacion",
    "pedir_datos_faltantes_cotizacion": "esperar_respuesta_cliente",
    "cotizacion_lista_para_asesor": "validando_cumplimiento",
    "preparar_proforma": "pedir_datos_faltantes_proforma",
    "pedir_datos_faltantes_proforma": "esperar_respuesta_cliente",
    "proforma_lista_para_asesor": "pago_pendiente",
    "rediagnostico_o_alternativa": "validar_necesidad_clara",
    "seguimiento": "esperar_respuesta_cliente",
}


# ============================================================
# UTILIDADES BÁSICAS
# ============================================================

def _safe_str(value: Any) -> str:
    """
    Convierte un valor a string limpio.
    """
    return "" if value is None else str(value).strip()


def _has_value(value: Any) -> bool:
    """
    Indica si un campo tiene valor útil.
    """
    return value not in [None, "", [], {}]


def _get_session_dict(session: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Obtiene un diccionario seguro desde la sesión.
    """
    value = session.get(key)

    if isinstance(value, dict):
        return value

    return {}


def _get_active_product(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Obtiene el producto activo desde la sesión.

    Soporta:
    - last_selected_product
    - last_selected_product_code
    """
    if not isinstance(session, dict):
        return None

    product = session.get("last_selected_product")

    if isinstance(product, dict) and product.get("codigo"):
        return product

    product_code = session.get("last_selected_product_code")

    if product_code:
        return {
            "codigo": product_code,
        }

    return None


def _get_commercial_data(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene datos comerciales estructurados.
    """
    data = session.get("commercial_data")

    if isinstance(data, dict):
        return data

    return {}


# ============================================================
# LECTURA DEL COMMERCIAL SPINE
# ============================================================

def get_commercial_spine() -> Dict[str, Any]:
    """
    Devuelve el Commercial Spine cargado desde NIA OS.
    """
    spine = get_commercial_spine_process()

    if not isinstance(spine, dict):
        return {}

    return spine


def get_commercial_spine_states() -> List[str]:
    """
    Devuelve la lista de estados definidos en master_flow.
    """
    spine = get_commercial_spine()
    master_flow = spine.get("master_flow", [])

    states: List[str] = []

    if not isinstance(master_flow, list):
        return states

    for step in master_flow:
        if isinstance(step, dict) and step.get("state"):
            states.append(str(step["state"]))

    return states


def is_valid_spine_state(state: str) -> bool:
    """
    Valida si un estado existe dentro del Commercial Spine.
    """
    state = _safe_str(state)

    if not state:
        return False

    return state in get_commercial_spine_states()


def get_spine_step_definition(state: str) -> Dict[str, Any]:
    """
    Devuelve la definición completa de un estado del master_flow.
    """
    state = _safe_str(state)
    spine = get_commercial_spine()
    master_flow = spine.get("master_flow", [])

    if not isinstance(master_flow, list):
        return {}

    for step in master_flow:
        if isinstance(step, dict) and step.get("state") == state:
            return deepcopy(step)

    return {}


# ============================================================
# MAPEO DE ESTADOS
# ============================================================

def map_internal_state_to_spine_state(
    internal_state: Optional[str],
    session: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Convierte un estado interno actual de NIA a un estado oficial
    del Commercial Spine.

    Si no existe estado interno pero hay producto activo, asumimos:
    producto_identificado.

    Si no hay suficiente información, retornamos:
    leer_contexto.
    """
    normalized_state = _safe_str(internal_state)

    if normalized_state in INTERNAL_TO_SPINE_STATE:
        return INTERNAL_TO_SPINE_STATE[normalized_state]

    session = session or {}

    # Si no hay estado explícito pero sí producto activo,
    # el Spine debe ubicarse en producto_identificado.
    if _get_active_product(session):
        return "producto_identificado"

    return "leer_contexto"


def get_next_spine_state(current_spine_state: str) -> str:
    """
    Devuelve siguiente estado sugerido según el estado actual.
    """
    current_spine_state = _safe_str(current_spine_state)

    if current_spine_state in SPINE_NEXT_STEP:
        return SPINE_NEXT_STEP[current_spine_state]

    step_definition = get_spine_step_definition(current_spine_state)
    next_state = step_definition.get("next_state")

    if next_state:
        return str(next_state)

    return "esperar_respuesta_cliente"


# ============================================================
# DATOS FALTANTES PARA COTIZACIÓN
# ============================================================

def calculate_quote_missing_fields(
    session: Dict[str, Any],
    enforce_spine_required_fields: bool = False,
) -> List[str]:
    """
    Calcula datos faltantes para cotización.

    Regla comercial actual:
    - Si NO hay teléfono del canal:
      requerimos producto, nombre, empresa y correo o teléfono.

    - Si SÍ hay teléfono del canal:
      producto + teléfono del canal bastan para dejar la cotización viable.
      Nombre y empresa pueden pedirse como datos opcionales, pero NO bloquean.

    Alineación con Don Andrés:
    Si el cliente no entrega datos, se toma el número por el cual escribió
    y a ese número se le envía la cotización.

    Nota:
    El Commercial Spine define como required_fields:
    producto, cantidad, nombre, empresa, correo, ciudad.

    Sin embargo, para no frenar el flujo comercial actual, esta
    integración NO obliga cantidad ni ciudad todavía.

    Más adelante, cuando Don Andrés lo confirme, podemos activar:
    enforce_spine_required_fields=True
    """
    missing: List[str] = []

    product = _get_active_product(session)
    commercial_data = _get_commercial_data(session)

    if not product:
        missing.append("producto")

    has_channel_phone = bool(
        session.get("channel_contact_phone")
        or session.get("commercial_contact_source") == "channel_phone"
    )

    has_contact = bool(
        commercial_data.get("correo")
        or commercial_data.get("telefono")
        or session.get("channel_contact_phone")
    )

    # ------------------------------------------------------------
    # Regla comercial:
    # Si tenemos teléfono del canal, nombre y empresa NO bloquean
    # la cotización.
    #
    # Se pueden pedir como datos opcionales para mejorar la solicitud,
    # pero no impiden dejar la cotización en proceso/lista.
    # ------------------------------------------------------------
    if not has_channel_phone:
        if not commercial_data.get("nombre_cliente"):
            missing.append("nombre")

        if not commercial_data.get("empresa"):
            missing.append("empresa")

    if not has_contact:
        missing.append("correo o teléfono")

    if enforce_spine_required_fields:
        if not commercial_data.get("cantidad"):
            missing.append("cantidad")

        if not commercial_data.get("ciudad"):
            missing.append("ciudad")

        # El Spine pide correo. Hoy aceptamos correo o teléfono.
        # Si se activa modo estricto, correo sí sería obligatorio.
        if not commercial_data.get("correo"):
            if "correo o teléfono" in missing:
                missing.remove("correo o teléfono")
            missing.append("correo")

    return missing


def has_complete_minimum_quote_data(session: Dict[str, Any]) -> bool:
    """
    Indica si NIA tiene los datos mínimos actuales para dejar
    una solicitud de cotización en proceso/lista.
    """
    return len(calculate_quote_missing_fields(session)) == 0


# ============================================================
# ACTUALIZACIÓN DEL ESTADO COMERCIAL EN SESIÓN
# ============================================================

def build_commercial_process_snapshot(
    session: Dict[str, Any],
    detected_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Construye una vista compacta del estado comercial actual.

    Esta vista es útil para:
    - guardar en memoria
    - depurar el flujo
    - alinear el estado interno con el Spine
    """
    if not isinstance(session, dict):
        session = {}

    internal_state = session.get("estado_negociacion")
    spine_state = map_internal_state_to_spine_state(
        internal_state=internal_state,
        session=session,
    )
    next_state = get_next_spine_state(spine_state)
    missing_fields = calculate_quote_missing_fields(session)

    active_product = _get_active_product(session)
    commercial_data = _get_commercial_data(session)

    return {
        "process_id": COMMERCIAL_SPINE_ID,
        "estado_negociacion": internal_state,
        "commercial_process_state": spine_state,
        "ultimo_paso": spine_state,
        "siguiente_paso": next_state,
        "intencion_actual": detected_intent or session.get("intent"),
        "datos_faltantes": missing_fields,
        "datos_cotizacion_completos": len(missing_fields) == 0,
        "producto_activo_codigo": (
            active_product.get("codigo")
            if isinstance(active_product, dict)
            else None
        ),
        "commercial_data": deepcopy(commercial_data),
    }


def update_commercial_process_state(
    session: Dict[str, Any],
    detected_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Actualiza la sesión con los campos oficiales del proceso comercial.

    Campos que agrega/actualiza:
    - commercial_process_id
    - commercial_process_state
    - ultimo_paso
    - siguiente_paso
    - datos_faltantes
    - intencion_actual

    Este método NO guarda en MongoDB por sí mismo.
    El caller debe ejecutar save_session(session).
    """
    if not isinstance(session, dict):
        return session

    snapshot = build_commercial_process_snapshot(
        session=session,
        detected_intent=detected_intent,
    )

    session["commercial_process_id"] = snapshot["process_id"]
    session["commercial_process_state"] = snapshot["commercial_process_state"]
    session["ultimo_paso"] = snapshot["ultimo_paso"]
    session["siguiente_paso"] = snapshot["siguiente_paso"]
    session["datos_faltantes"] = snapshot["datos_faltantes"]
    session["intencion_actual"] = snapshot["intencion_actual"]

    return session


# ============================================================
# RESPUESTAS / DEBUG
# ============================================================

def summarize_commercial_process_state(session: Dict[str, Any]) -> str:
    """
    Devuelve resumen legible del estado comercial actual.
    Útil para logs o pruebas.
    """
    snapshot = build_commercial_process_snapshot(session)

    return (
        f"Estado interno: {snapshot.get('estado_negociacion')} | "
        f"Spine: {snapshot.get('commercial_process_state')} | "
        f"Siguiente: {snapshot.get('siguiente_paso')} | "
        f"Faltantes: {snapshot.get('datos_faltantes')}"
    )