# ============================================================
# memory/mongo_session_store.py
# ============================================================
# RESPONSABILIDAD:
# Persistir sesiones conversacionales de NIA en MongoDB.
#
# Por qué existe:
# - En local, la memoria en RAM funciona.
# - En Azure, la memoria en RAM NO es confiable porque pueden existir
#   varios workers, reinicios o reciclado de procesos.
# - Para que NIA recuerde producto activo, última pregunta,
#   slot pendiente y contexto comercial, la sesión debe vivir
#   en MongoDB.
#
# TTL:
# - Las sesiones se eliminan automáticamente después de 8 días
#   sin actualización.
# - 8 días = 691200 segundos.
#
# Este módulo NO maneja lógica conversacional.
# Este módulo NO decide intenciones.
# Solo guarda, lee y elimina sesiones.
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

SESSION_TTL_SECONDS = int(os.getenv("NIA_SESSION_TTL_SECONDS", "691200"))
SESSION_COLLECTION_NAME = os.getenv("NIA_SESSION_COLLECTION", "nia_sessions")

# Permite apagar Mongo sessions si algún día se necesita depurar localmente.
# Por defecto queda encendido porque Azure lo necesita.
ENABLE_MONGO_SESSION_MEMORY = (
    os.getenv("NIA_ENABLE_MONGO_SESSION_MEMORY", "true").lower().strip()
    not in ["0", "false", "no", "off"]
)

_indexes_ready = False


# ============================================================
# UTILIDADES
# ============================================================

def _utc_now() -> datetime:
    """
    Devuelve datetime UTC compatible con MongoDB TTL.
    """
    return datetime.now(timezone.utc)


def _get_collection():
    """
    Obtiene colección de sesiones.
    Reutiliza la conexión oficial del proyecto en services/mongo.py.
    """
    db = get_db()
    return db[SESSION_COLLECTION_NAME]


def _is_enabled() -> bool:
    """
    Indica si la persistencia Mongo está habilitada.
    """
    return ENABLE_MONGO_SESSION_MEMORY


def _clean_session_for_return(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Limpia campos internos de Mongo antes de devolver la sesión
    al motor conversacional.
    """
    clean = deepcopy(document)

    clean.pop("_id", None)
    clean.pop("updated_at_date", None)
    clean.pop("created_at_date", None)

    return clean


def ensure_session_indexes() -> bool:
    """
    Crea índices necesarios para sesiones.

    Índices:
    1. session_id único.
    2. updated_at_date con TTL de 8 días.

    MongoDB ejecuta el TTL de forma asíncrona, por eso una sesión
    puede tardar un poco más en desaparecer físicamente.
    """
    global _indexes_ready

    if _indexes_ready:
        return True

    if not _is_enabled():
        return False

    try:
        collection = _get_collection()

        collection.create_index(
            "session_id",
            unique=True,
            name="idx_nia_sessions_session_id",
        )

        collection.create_index(
            "updated_at_date",
            expireAfterSeconds=SESSION_TTL_SECONDS,
            name="ttl_nia_sessions_updated_at_date",
        )

        _indexes_ready = True
        logger.info(
            "Índices de sesiones NIA verificados. Collection=%s TTL=%s",
            SESSION_COLLECTION_NAME,
            SESSION_TTL_SECONDS,
        )
        return True

    except Exception as error:
        # No tumbamos NIA si Mongo falla; conversation_memory.py
        # conservará fallback en RAM.
        logger.warning("No se pudieron crear/verificar índices de sesión: %s", error)
        return False


# ============================================================
# OPERACIONES PRINCIPALES
# ============================================================

def save_session_to_mongo(session: Dict[str, Any]) -> bool:
    """
    Guarda o actualiza una sesión en MongoDB.

    Retorna:
    - True si guardó correctamente.
    - False si Mongo no está disponible o falta session_id.
    """
    if not _is_enabled():
        return False

    if not isinstance(session, dict):
        return False

    session_id = session.get("session_id")

    if not session_id:
        return False

    try:
        ensure_session_indexes()

        now = _utc_now()
        document = deepcopy(session)

        # Campo Date real para TTL.
        document["updated_at_date"] = now

        # Solo se usa como metadata visual. El TTL depende de updated_at_date.
        if not document.get("created_at_date"):
            document["created_at_date"] = now

        collection = _get_collection()

        collection.update_one(
            {"session_id": session_id},
            {"$set": document},
            upsert=True,
        )

        return True

    except PyMongoError as error:
        logger.warning("Error Mongo guardando sesión %s: %s", session_id, error)
        return False

    except Exception as error:
        logger.warning("Error inesperado guardando sesión %s: %s", session_id, error)
        return False


def get_session_from_mongo(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Recupera una sesión desde MongoDB por session_id.
    """
    if not _is_enabled():
        return None

    session_id = str(session_id or "").strip()

    if not session_id:
        return None

    try:
        ensure_session_indexes()

        collection = _get_collection()
        document = collection.find_one({"session_id": session_id})

        if not document:
            return None

        return _clean_session_for_return(document)

    except PyMongoError as error:
        logger.warning("Error Mongo leyendo sesión %s: %s", session_id, error)
        return None

    except Exception as error:
        logger.warning("Error inesperado leyendo sesión %s: %s", session_id, error)
        return None


def delete_session_from_mongo(session_id: str) -> bool:
    """
    Elimina una sesión desde MongoDB.

    Se usa cuando el usuario cierra conversación manualmente.
    """
    if not _is_enabled():
        return False

    session_id = str(session_id or "").strip()

    if not session_id:
        return False

    try:
        collection = _get_collection()
        collection.delete_one({"session_id": session_id})
        return True

    except PyMongoError as error:
        logger.warning("Error Mongo eliminando sesión %s: %s", session_id, error)
        return False

    except Exception as error:
        logger.warning("Error inesperado eliminando sesión %s: %s", session_id, error)
        return False


def session_store_health() -> Dict[str, Any]:
    """
    Diagnóstico rápido del store de sesiones.

    Útil para pruebas manuales:
    python -c "from memory.mongo_session_store import session_store_health; print(session_store_health())"
    """
    if not _is_enabled():
        return {
            "ok": False,
            "enabled": False,
            "reason": "NIA_ENABLE_MONGO_SESSION_MEMORY está desactivado",
        }

    try:
        ensure_session_indexes()

        collection = _get_collection()

        return {
            "ok": True,
            "enabled": True,
            "database": get_db().name,
            "collection": SESSION_COLLECTION_NAME,
            "ttl_seconds": SESSION_TTL_SECONDS,
            "estimated_documents": collection.estimated_document_count(),
        }

    except Exception as error:
        return {
            "ok": False,
            "enabled": True,
            "collection": SESSION_COLLECTION_NAME,
            "ttl_seconds": SESSION_TTL_SECONDS,
            "error": str(error),
        }