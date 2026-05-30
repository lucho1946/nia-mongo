# ============================================================
# memory/commercial_opportunity_store.py
# ============================================================
# RESPONSABILIDAD:
# Persistir oportunidades comerciales generadas por NIA.
#
# Entrada principal:
# - commercial_handoff
#
# Salida:
# - Documento guardado en MongoDB, colección:
#   commercial_opportunities
#
# Este módulo NO decide conversación.
# Este módulo NO crea cotizaciones reales todavía.
# Este módulo NO se conecta a Bitrix todavía.
#
# Objetivo:
# Dejar una oportunidad comercial estructurada y consultable,
# lista para integración futura con:
# - asesor
# - Bitrix
# - CRM
# - panel comercial
# - automatización de cotizaciones/proformas
# ============================================================

from __future__ import annotations

import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo.errors import PyMongoError

from services.mongo import get_db


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN
# ============================================================

OPPORTUNITY_COLLECTION_NAME = os.getenv(
    "NIA_COMMERCIAL_OPPORTUNITY_COLLECTION",
    "commercial_opportunities",
)

ENABLE_COMMERCIAL_OPPORTUNITY_STORE = (
    os.getenv("NIA_ENABLE_COMMERCIAL_OPPORTUNITY_STORE", "true").lower().strip()
    not in ["0", "false", "no", "off"]
)

_indexes_ready = False


# ============================================================
# UTILIDADES
# ============================================================

def _utc_now() -> datetime:
    """
    Fecha UTC como datetime real para MongoDB.
    """
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """
    Fecha UTC en formato ISO para trazabilidad legible.
    """
    return _utc_now().isoformat()


def _is_enabled() -> bool:
    """
    Permite desactivar esta persistencia por variable de entorno.
    """
    return ENABLE_COMMERCIAL_OPPORTUNITY_STORE


def _get_collection():
    """
    Obtiene la colección oficial de oportunidades comerciales.
    Reutiliza la conexión centralizada del proyecto.
    """
    db = get_db()
    return db[OPPORTUNITY_COLLECTION_NAME]


def _safe_str(value: Any) -> Optional[str]:
    """
    Convierte un valor a string limpio.
    Retorna None si viene vacío.
    """
    if value in [None, "", [], {}]:
        return None

    text = str(value).strip()

    return text if text else None


def _clean_for_return(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Limpia campos internos de Mongo antes de devolver el documento.
    """
    clean = deepcopy(document)
    clean.pop("_id", None)
    return clean


def _build_opportunity_id(handoff: Dict[str, Any]) -> Optional[str]:
    """
    Construye un ID estable para upsert.

    Regla:
    - handoff_id ya viene con tipo + session_id.
    - Eso permite actualizar la misma oportunidad si el flujo evoluciona.
    """
    handoff_id = _safe_str(handoff.get("handoff_id"))

    if handoff_id:
        return handoff_id

    handoff_type = _safe_str(handoff.get("tipo"))
    session_id = _safe_str(handoff.get("session_id"))

    if handoff_type and session_id:
        return f"{handoff_type}_{session_id}"

    return None


def normalize_commercial_opportunity(
    handoff: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Normaliza el commercial_handoff a documento de oportunidad.

    No inventa datos.
    Solo copia campos existentes y agrega metadata de persistencia.
    """
    if not isinstance(handoff, dict):
        return None

    opportunity_id = _build_opportunity_id(handoff)

    if not opportunity_id:
        return None

    now = _utc_now()

    document = deepcopy(handoff)

    document["opportunity_id"] = opportunity_id
    document["handoff_id"] = _safe_str(handoff.get("handoff_id")) or opportunity_id

    # Tipo esperado: cotizacion / proforma.
    document["tipo"] = _safe_str(handoff.get("tipo"))

    # Estado accionable.
    document["estado"] = _safe_str(handoff.get("estado")) or "lista_para_asesor"
    document["siguiente_paso"] = _safe_str(handoff.get("siguiente_paso"))

    # Fechas para auditoría.
    document["created_at"] = _safe_str(handoff.get("created_at")) or _now_iso()
    document["updated_at"] = _now_iso()
    document["created_at_date"] = handoff.get("created_at_date") or now
    document["updated_at_date"] = now

    # Fuente del documento.
    document["source"] = "nia_commercial_handoff"
    document["schema_version"] = "commercial_opportunity_v1"

    # Campos de deduplicación/consulta rápida.
    document["session_id"] = _safe_str(handoff.get("session_id"))
    document["canal"] = _safe_str(handoff.get("canal"))
    document["cliente_id"] = _safe_str(handoff.get("cliente_id"))
    document["contact_source"] = _safe_str(handoff.get("contact_source"))

    document["producto_codigo"] = _safe_str(handoff.get("producto_codigo"))
    document["producto_referencia"] = _safe_str(handoff.get("producto_referencia"))
    document["producto_nombre"] = _safe_str(handoff.get("producto_nombre"))
    document["producto_marca"] = _safe_str(handoff.get("producto_marca"))

    document["cliente"] = _safe_str(handoff.get("cliente"))
    document["empresa"] = _safe_str(handoff.get("empresa"))
    document["correo"] = _safe_str(handoff.get("correo"))
    document["telefono"] = _safe_str(handoff.get("telefono"))
    document["documento_fiscal"] = _safe_str(handoff.get("documento_fiscal"))
    document["nit"] = _safe_str(handoff.get("nit"))
    document["rut"] = _safe_str(handoff.get("rut"))

    return document


# ============================================================
# ÍNDICES
# ============================================================

def ensure_commercial_opportunity_indexes() -> bool:
    """
    Crea índices básicos para oportunidades comerciales.

    Índices:
    1. opportunity_id único.
    2. session_id.
    3. tipo + estado.
    4. producto_codigo.
    5. created_at_date.
    """
    global _indexes_ready

    if _indexes_ready:
        return True

    if not _is_enabled():
        return False

    try:
        collection = _get_collection()

        collection.create_index(
            "opportunity_id",
            unique=True,
            name="idx_commercial_opportunities_opportunity_id",
        )

        collection.create_index(
            "session_id",
            name="idx_commercial_opportunities_session_id",
        )

        collection.create_index(
            [("tipo", 1), ("estado", 1)],
            name="idx_commercial_opportunities_tipo_estado",
        )

        collection.create_index(
            "producto_codigo",
            name="idx_commercial_opportunities_producto_codigo",
        )

        collection.create_index(
            "created_at_date",
            name="idx_commercial_opportunities_created_at_date",
        )

        _indexes_ready = True

        logger.info(
            "Índices de oportunidades comerciales verificados. Collection=%s",
            OPPORTUNITY_COLLECTION_NAME,
        )

        return True

    except Exception as error:
        # No tumbamos NIA por una falla de persistencia.
        logger.warning(
            "No se pudieron crear/verificar índices de oportunidades comerciales: %s",
            error,
        )
        return False


# ============================================================
# OPERACIONES PRINCIPALES
# ============================================================

def save_commercial_opportunity(
    handoff: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Guarda o actualiza una oportunidad comercial en MongoDB.

    Retorna:
    - documento guardado si todo salió bien.
    - None si no se pudo guardar.
    """
    if not _is_enabled():
        return None

    document = normalize_commercial_opportunity(handoff)

    if not document:
        return None

    opportunity_id = document.get("opportunity_id")

    try:
        ensure_commercial_opportunity_indexes()

        collection = _get_collection()

        collection.update_one(
            {"opportunity_id": opportunity_id},
            {"$set": document},
            upsert=True,
        )

        saved = collection.find_one({"opportunity_id": opportunity_id})

        if not saved:
            return document

        return _clean_for_return(saved)

    except PyMongoError as error:
        logger.warning(
            "Error Mongo guardando oportunidad comercial %s: %s",
            opportunity_id,
            error,
        )
        return None

    except Exception as error:
        logger.warning(
            "Error inesperado guardando oportunidad comercial %s: %s",
            opportunity_id,
            error,
        )
        return None


def get_commercial_opportunity(
    opportunity_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Recupera una oportunidad por opportunity_id.
    """
    if not _is_enabled():
        return None

    opportunity_id = _safe_str(opportunity_id)

    if not opportunity_id:
        return None

    try:
        ensure_commercial_opportunity_indexes()

        collection = _get_collection()
        document = collection.find_one({"opportunity_id": opportunity_id})

        if not document:
            return None

        return _clean_for_return(document)

    except PyMongoError as error:
        logger.warning(
            "Error Mongo leyendo oportunidad comercial %s: %s",
            opportunity_id,
            error,
        )
        return None

    except Exception as error:
        logger.warning(
            "Error inesperado leyendo oportunidad comercial %s: %s",
            opportunity_id,
            error,
        )
        return None


def find_commercial_opportunities_by_session(
    session_id: str,
) -> list[Dict[str, Any]]:
    """
    Lista oportunidades asociadas a una sesión.
    """
    if not _is_enabled():
        return []

    session_id = _safe_str(session_id)

    if not session_id:
        return []

    try:
        ensure_commercial_opportunity_indexes()

        collection = _get_collection()

        cursor = collection.find({"session_id": session_id}).sort(
            "created_at_date",
            1,
        )

        return [_clean_for_return(document) for document in cursor]

    except PyMongoError as error:
        logger.warning(
            "Error Mongo listando oportunidades por sesión %s: %s",
            session_id,
            error,
        )
        return []

    except Exception as error:
        logger.warning(
            "Error inesperado listando oportunidades por sesión %s: %s",
            session_id,
            error,
        )
        return []