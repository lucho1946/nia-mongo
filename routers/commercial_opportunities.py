# ============================================================
# routers/commercial_opportunities.py
# ============================================================
# RESPONSABILIDAD:
# Exponer endpoints internos para consultar oportunidades
# comerciales generadas por NIA y guardadas en MongoDB.
#
# Este router NO:
# - crea cotizaciones reales;
# - conecta Bitrix;
# - modifica oportunidades;
# - decide conversación.
#
# Solo permite consultar lo que NIA ya dejó guardado:
# commercial_handoff -> commercial_opportunities.
#
# Uso futuro:
# - revisión interna;
# - panel comercial;
# - integración Bitrix/CRM;
# - trazabilidad de pruebas de Don Andrés.
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Path

from memory.commercial_opportunity_store import (
    get_commercial_opportunity,
    find_commercial_opportunities_by_session,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/commercial-opportunities",
    tags=["Commercial Opportunities"],
)


@router.get("/{opportunity_id}")
def get_opportunity_by_id(
    opportunity_id: str = Path(
        ...,
        min_length=1,
        description="ID de oportunidad comercial generado por NIA.",
    )
) -> Dict[str, Any]:
    """
    Consulta una oportunidad comercial por opportunity_id.

    Ejemplo:
    /commercial-opportunities/cotizacion_xxxxx
    /commercial-opportunities/proforma_xxxxx
    """
    try:
        opportunity = get_commercial_opportunity(opportunity_id)

        if not opportunity:
            raise HTTPException(
                status_code=404,
                detail="Oportunidad comercial no encontrada.",
            )

        return {
            "ok": True,
            "opportunity_id": opportunity_id,
            "opportunity": opportunity,
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "Error consultando oportunidad comercial por ID %s",
            opportunity_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando oportunidad comercial: {error}",
        )


@router.get("/session/{session_id}")
def get_opportunities_by_session(
    session_id: str = Path(
        ...,
        min_length=1,
        description="Session ID de la conversación NIA.",
    )
) -> Dict[str, Any]:
    """
    Lista oportunidades comerciales asociadas a una sesión.

    Esto permite revisar qué oportunidades generó una conversación.
    """
    try:
        items = find_commercial_opportunities_by_session(session_id)

        return {
            "ok": True,
            "session_id": session_id,
            "total": len(items),
            "items": items,
        }

    except Exception as error:
        logger.exception(
            "Error consultando oportunidades comerciales por session_id %s",
            session_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando oportunidades por sesión: {error}",
        )