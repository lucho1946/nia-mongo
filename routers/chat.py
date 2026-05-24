# ============================================================
# routers/chat.py
# ============================================================
# Responsabilidad única: endpoint /chat conversacional.
#
# VERSIÓN 1.0 — MIGRACIÓN A ORQUESTADOR NIA OS
#
# Cambios:
# - /chat deja de usar services.ai como cerebro principal.
# - /chat ahora usa orchestration.nia_orchestrator.process_message().
# - Se conserva el contrato público ChatResponse para no romper frontend.
# - Se mantiene trazabilidad Azure.
# - Se conserva endpoint DELETE /chat/{session_id}.
#
# Enfoque:
# - Catálogo real como fuente de verdad.
# - No inventar productos.
# - Máximo 3 preguntas técnicas.
# - No exponer configuración interna de NIA al cliente.
# - No recomendar productos incompatibles.
# ============================================================

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.schemas import ChatRequest, ChatResponse
from orchestration.chat_response_adapter import process_chat_request
from memory.conversation_memory import clear_session
from services.audit import registrar_traza_azure

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


# ============================================================
# TRAZABILIDAD
# ============================================================

def registrar_salida_chat(
    session_id: str,
    respuesta: str,
    estado: str,
    preguntas_hechas: int,
    productos_count: int = 0,
    requiere_accion: str | None = None,
    etapa: str = "chat.output",
) -> None:
    """
    Registra la salida final del flujo /chat.
    """
    registrar_traza_azure(
        etapa,
        {
            "session_id": session_id,
            "respuesta": respuesta,
            "estado": estado,
            "preguntas_hechas": preguntas_hechas,
            "productos_count": productos_count,
            "requiere_accion": requiere_accion,
        },
    )


# ============================================================
# ENDPOINT PRINCIPAL
# ============================================================

@router.post("/chat", response_model=ChatResponse)
def chat(p: ChatRequest) -> ChatResponse:
    """
    Endpoint principal del chatbot NIA.

    Flujo nuevo:
    request API
    → chat_response_adapter
    → nia_orchestrator.process_message()
    → ChatResponse compatible con frontend
    """
    mensaje = p.mensaje.strip()

    registrar_traza_azure(
        "chat.input",
        {
            "session_id": p.session_id,
            "canal": p.canal,
            "cliente_id": p.cliente_id,
            "mensaje": mensaje,
            "archivo_nombre": getattr(p, "archivo_nombre", None),
            "archivo_tipo": getattr(p, "archivo_tipo", None),
            "archivo_ruta": getattr(p, "archivo_ruta", None),
            "archivo_mimetype": getattr(p, "archivo_mimetype", None),
            "engine": "nia_orchestrator",
        },
    )

    try:
        response = process_chat_request(p)

    except Exception as error:
        logger.exception("Error procesando /chat con orquestador: %s", error)

        registrar_traza_azure(
            "chat.output.error",
            {
                "session_id": p.session_id,
                "mensaje": mensaje,
                "error": str(error),
                "engine": "nia_orchestrator",
            },
        )

        raise HTTPException(
            status_code=500,
            detail="Error procesando la consulta. Intenta nuevamente.",
        )

    registrar_salida_chat(
        session_id=response.session_id,
        respuesta=response.respuesta,
        estado=response.estado,
        preguntas_hechas=response.preguntas_hechas,
        productos_count=len(response.productos),
        requiere_accion=response.requiere_accion,
        etapa="chat.output.final",
    )

    return response


# ============================================================
# CIERRE DE SESIÓN
# ============================================================

@router.delete("/chat/{session_id}")
def cerrar_chat(session_id: str):
    """
    Cierra una sesión de chat manualmente.

    Nota:
    En esta etapa el orquestador usa memory/conversation_memory.py.
    Cuando migremos la memoria a MongoDB, este cierre se alineará
    con la colección sessions y TTL.
    """
    deleted = clear_session(session_id)

    registrar_traza_azure(
        "chat.session.closed",
        {
            "session_id": session_id,
            "deleted": deleted,
            "engine": "nia_orchestrator",
        },
    )

    return {
        "ok": True,
        "session_id": session_id,
        "deleted": deleted,
    }