# ============================================================
# orchestration/chat_response_adapter.py
# ============================================================
# RESPONSABILIDAD:
# Adaptar la salida del orquestador NIA OS al contrato público
# del endpoint /chat.
#
# Este archivo permite migrar routers/chat.py al cerebro nuevo
# sin romper el frontend.
#
# Entrada:
# - ChatRequest
#
# Salida:
# - ChatResponse
#
# Este módulo NO decide intención.
# Este módulo NO busca productos.
# Este módulo NO llama OpenAI directamente.
# Solo conecta:
#   request API → process_message() → ChatResponse
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.schemas import ChatRequest, ChatResponse, ProductoResponse
from orchestration.nia_orchestrator import process_message


# ============================================================
# UTILIDADES
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte cualquier valor a string seguro.
    """
    if value is None:
        return default

    try:
        return str(value).strip()
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """
    Convierte cualquier valor a entero seguro.
    """
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_producto_from_card(card: Dict[str, Any]) -> ProductoResponse:
    """
    Convierte una card del response_engine en ProductoResponse.

    Las cards del orquestador son más compactas que el producto completo.
    Los campos faltantes se dejan con default para no romper frontend.
    """
    return ProductoResponse(
        codigo=_safe_str(card.get("codigo")),
        referencia=_safe_str(card.get("referencia")),
        ref_alternativa=_safe_str(card.get("ref_alternativa")),
        nombre=_safe_str(card.get("nombre")),
        descripcion=_safe_str(card.get("descripcion")),
        marca=_safe_str(card.get("marca")),
        nivel_0=_safe_str(card.get("nivel_0")),
        nivel_1=_safe_str(card.get("nivel_1")),
        nivel_2=_safe_str(card.get("nivel_2")),
        nivel_3=_safe_str(card.get("nivel_3")),
        nivel_4=_safe_str(card.get("nivel_4")),
        precio=_safe_str(card.get("precio"), "Consultarnos"),
        disponibilidad=_safe_str(
            card.get("disponibilidad"),
            "Consultar disponibilidad",
        ),
        tiempo_entrega=_safe_str(card.get("tiempo_entrega")),
        caracteristicas=card.get("caracteristicas", []),
        aplicaciones=_safe_str(card.get("aplicaciones")),
        dimension=_safe_str(card.get("dimension")),
        peso=card.get("peso"),
        equivalente=_safe_str(card.get("equivalente")),
        equivalente_2=_safe_str(card.get("equivalente_2")),
        score_oportunidad=card.get("score_oportunidad"),
        tipo_sku=_safe_str(card.get("tipo_sku")),
    )


def _extract_productos(orchestrator_result: Dict[str, Any]) -> List[ProductoResponse]:
    """
    Extrae productos desde la respuesta del orquestador.

    El response_engine retorna normalmente:
    - cards: [...]
    """
    cards = orchestrator_result.get("cards", [])

    if not isinstance(cards, list):
        return []

    productos: List[ProductoResponse] = []

    for card in cards:
        if not isinstance(card, dict):
            continue

        productos.append(_build_producto_from_card(card))

    return productos


def _detect_estado(orchestrator_result: Dict[str, Any], productos: List[ProductoResponse]) -> str:
    """
    Traduce estado interno del orquestador al estado público del chat.

    Estados actuales esperados por frontend:
    - recopilando
    - completado
    - cerrado
    """
    if orchestrator_result.get("estado") == "cerrado":
        return "cerrado"

    if orchestrator_result.get("needs_clarification") is True:
        return "recopilando"

    if productos:
        return "completado"

    decision_reason = _safe_str(orchestrator_result.get("decision_reason"))

    if decision_reason in {
        "public_safe_internal_nia_query",
        "no_compatible_results",
        "no_compatible_motor_with_power_voltage",
        "no_compatible_variador_with_power_voltage",
        "no_compatible_torquimetro_with_measure",
    }:
        return "completado"

    intent = _safe_str(orchestrator_result.get("intent"))

    if intent == "saludo":
        return "recopilando"

    return "completado"


def _detect_requiere_accion(orchestrator_result: Dict[str, Any]) -> Optional[str]:
    """
    Traduce acciones especiales futuras.
    """
    requiere_accion = orchestrator_result.get("requiere_accion")

    if requiere_accion:
        return _safe_str(requiere_accion)

    decision_reason = _safe_str(orchestrator_result.get("decision_reason"))

    if decision_reason == "escalar_asesor":
        return "escalar_asesor"

    if decision_reason == "generar_preorden":
        return "generar_preorden"

    return None


def adapt_orchestrator_result_to_chat_response(
    orchestrator_result: Dict[str, Any],
) -> ChatResponse:
    """
    Convierte la salida del orquestador a ChatResponse.
    """
    productos = _extract_productos(orchestrator_result)

    session_id = _safe_str(
        orchestrator_result.get("session_id"),
        "sin_session",
    )

    respuesta = _safe_str(
        orchestrator_result.get("response"),
        "¿Me puedes dar un poco más de detalle para ayudarte mejor?",
    )

    estado = _detect_estado(
        orchestrator_result=orchestrator_result,
        productos=productos,
    )

    preguntas_hechas = _safe_int(
        orchestrator_result.get("preguntas_hechas"),
        0,
    )

    requiere_accion = _detect_requiere_accion(orchestrator_result)

    return ChatResponse(
        session_id=session_id,
        respuesta=respuesta,
        estado=estado,
        preguntas_hechas=preguntas_hechas,
        productos=productos,
        requiere_accion=requiere_accion,

        # Metadata comercial.
        estado_negociacion=orchestrator_result.get("estado_negociacion"),
        commercial_process_state=orchestrator_result.get("commercial_process_state"),
        siguiente_paso=orchestrator_result.get("siguiente_paso"),
        datos_faltantes=orchestrator_result.get("datos_faltantes") or [],
        datos_faltantes_proforma=orchestrator_result.get("datos_faltantes_proforma") or [],

        # Handoff comercial estructurado.
        commercial_handoff=orchestrator_result.get("commercial_handoff"),
    )


def process_chat_request(request: ChatRequest) -> ChatResponse:
    """
    Punto de entrada para routers/chat.py.

    Ejecuta el cerebro nuevo:
    - orchestration.nia_orchestrator.process_message()

    y adapta su salida al contrato público del endpoint /chat.
    """
    message = _safe_str(request.mensaje)

    orchestrator_result = process_message(
    message=message,
    session_id=request.session_id,
    canal=request.canal,
    cliente_id=request.cliente_id,
)

    return adapt_orchestrator_result_to_chat_response(orchestrator_result)