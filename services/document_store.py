# ============================================================
# services/document_store.py
# ============================================================
# RESPONSABILIDAD:
# Persistencia de documentos técnicos de NIA en MongoDB Atlas.
#
# Esta capa guarda el resultado de knowledge/file_reader.py
# en una colección separada del catálogo real.
#
# Colección:
# - technical_documents
#
# IMPORTANTE:
# Este módulo NO recomienda productos.
# Este módulo NO consulta products_catalog.
# Este módulo NO responde al usuario.
# Este módulo NO se conecta todavía al orquestador.
#
# Regla de Don Andrés:
# - products_catalog = fuente de verdad para productos.
# - technical_documents = soporte técnico/documental.
# ============================================================

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .mongo import get_db

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN
# ============================================================

TECHNICAL_DOCUMENTS_COLLECTION = "technical_documents"


# ============================================================
# COLECCIÓN
# ============================================================

def get_technical_documents_collection():
    """
    Retorna la colección technical_documents usando la conexión
    centralizada de services.mongo.
    """
    return get_db()[TECHNICAL_DOCUMENTS_COLLECTION]


# ============================================================
# UTILIDADES
# ============================================================

def _now_utc() -> datetime:
    """
    Fecha/hora actual en UTC para MongoDB.
    """
    return datetime.now(timezone.utc)


def _safe_str(value: Any) -> str:
    """
    Convierte cualquier valor a string seguro.
    """
    if value is None:
        return ""

    try:
        return str(value).strip()
    except Exception:
        return ""


def _build_text_hash(text: str) -> str:
    """
    Genera hash estable del texto del documento.
    """
    text = _safe_str(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_doc_id(file_name: str, text_hash: str) -> str:
    """
    Genera ID lógico del documento.
    """
    raw = f"{file_name}:{text_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_text_preview(text: str, max_chars: int = 500) -> str:
    """
    Crea una vista previa corta del documento.
    """
    text = _safe_str(text)

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip()


def _sanitize_chunks(chunks: Any) -> List[Dict[str, Any]]:
    """
    Limpia chunks antes de guardarlos en MongoDB.
    """
    if not isinstance(chunks, list):
        return []

    sanitized: List[Dict[str, Any]] = []

    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            continue

        text = _safe_str(chunk.get("text"))

        if not text:
            continue

        sanitized.append({
            "chunk_id": _safe_str(chunk.get("chunk_id")) or f"chunk_{index:04d}",
            "text": text,
            "source": _safe_str(chunk.get("source")),
            "start_char": chunk.get("start_char"),
            "end_char": chunk.get("end_char"),
            "chars": chunk.get("chars") or len(text),
        })

    return sanitized


# ============================================================
# NORMALIZACIÓN DEL DOCUMENTO
# ============================================================

def build_document_record(
    file_result: Dict[str, Any],
    source_type: str = "manual",
    tags: Optional[List[str]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convierte el resultado de read_knowledge_file()
    en un documento listo para guardar en MongoDB.
    """
    if not isinstance(file_result, dict):
        raise ValueError("file_result debe ser un diccionario.")

    if not file_result.get("ok"):
        raise ValueError(
            f"No se puede guardar un archivo con error: {file_result.get('errors')}"
        )

    file_name = _safe_str(file_result.get("file_name"))
    file_path = _safe_str(file_result.get("file_path"))
    file_type = _safe_str(file_result.get("file_type"))
    text = _safe_str(file_result.get("text"))

    if not file_name:
        raise ValueError("file_result no tiene file_name.")

    if not text:
        raise ValueError("file_result no contiene texto extraído.")

    chunks = _sanitize_chunks(file_result.get("chunks", []))

    if not chunks:
        raise ValueError("file_result no contiene chunks válidos.")

    text_hash = _build_text_hash(text)
    doc_id = _build_doc_id(file_name=file_name, text_hash=text_hash)

    metadata = file_result.get("metadata", {}) or {}

    if not isinstance(metadata, dict):
        metadata = {}

    if extra_metadata:
        metadata = {
            **metadata,
            **extra_metadata,
        }

    now = _now_utc()

    return {
        "doc_id": doc_id,
        "file_name": file_name,
        "file_path": file_path,
        "file_type": file_type,
        "source_type": source_type,
        "tags": tags or [],
        "text_hash": text_hash,
        "text_preview": _build_text_preview(text),
        "chunks": chunks,
        "metadata": {
            **metadata,
            "chunk_count": len(chunks),
            "chars": len(text),
        },
        "created_at": now,
        "updated_at": now,
        "status": "active",
    }


# ============================================================
# OPERACIONES CRUD
# ============================================================

def save_document_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Guarda o actualiza un documento en MongoDB usando doc_id.
    """
    if not isinstance(record, dict):
        raise ValueError("record debe ser un diccionario.")

    doc_id = record.get("doc_id")

    if not doc_id:
        raise ValueError("record no contiene doc_id.")

    col = get_technical_documents_collection()

    existing = col.find_one({"doc_id": doc_id})
    now = _now_utc()

    if existing:
        record["created_at"] = existing.get("created_at", now)
        record["updated_at"] = now

        col.update_one(
            {"doc_id": doc_id},
            {"$set": record},
        )

        action = "updated"
    else:
        col.insert_one(record)
        action = "inserted"

    return {
        "ok": True,
        "action": action,
        "doc_id": doc_id,
        "file_name": record.get("file_name"),
        "chunk_count": len(record.get("chunks", [])),
        "collection": TECHNICAL_DOCUMENTS_COLLECTION,
    }


def save_file_result(
    file_result: Dict[str, Any],
    source_type: str = "manual",
    tags: Optional[List[str]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Recibe el resultado de read_knowledge_file() y lo guarda.
    """
    try:
        record = build_document_record(
            file_result=file_result,
            source_type=source_type,
            tags=tags,
            extra_metadata=extra_metadata,
        )

        return save_document_record(record)

    except Exception as error:
        logger.error(f"Error guardando documento técnico: {error}")

        return {
            "ok": False,
            "action": "error",
            "doc_id": None,
            "file_name": file_result.get("file_name") if isinstance(file_result, dict) else None,
            "chunk_count": 0,
            "collection": TECHNICAL_DOCUMENTS_COLLECTION,
            "errors": [str(error)],
        }


def save_folder_result(
    folder_result: Dict[str, Any],
    source_type: str = "manual",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Guarda todos los archivos exitosos de read_knowledge_folder().
    """
    if not isinstance(folder_result, dict):
        return {
            "ok": False,
            "summary": {
                "total_files": 0,
                "saved": 0,
                "errors": 1,
            },
            "results": [],
            "errors": ["folder_result debe ser un diccionario."],
        }

    files = folder_result.get("files", [])

    if not isinstance(files, list):
        files = []

    results = []

    for file_result in files:
        if not isinstance(file_result, dict):
            continue

        if not file_result.get("ok"):
            results.append({
                "ok": False,
                "file_name": file_result.get("file_name"),
                "errors": file_result.get("errors", []),
            })
            continue

        save_result = save_file_result(
            file_result=file_result,
            source_type=source_type,
            tags=tags,
        )

        results.append(save_result)

    saved = sum(1 for item in results if item.get("ok"))
    errors = len(results) - saved

    return {
        "ok": errors == 0,
        "summary": {
            "total_files": len(results),
            "saved": saved,
            "errors": errors,
        },
        "results": results,
        "errors": [
            error
            for item in results
            for error in item.get("errors", [])
        ],
    }


def get_document_by_doc_id(doc_id: str) -> Optional[Dict[str, Any]]:
    """
    Busca un documento por doc_id.
    """
    col = get_technical_documents_collection()
    doc = col.find_one({"doc_id": doc_id})

    if not doc:
        return None

    doc["_id"] = str(doc["_id"])
    return doc


def list_documents(
    source_type: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Lista documentos técnicos guardados.
    """
    col = get_technical_documents_collection()

    query: Dict[str, Any] = {
        "status": "active",
    }

    if source_type:
        query["source_type"] = source_type

    cursor = (
        col.find(
            query,
            {
                "_id": 1,
                "doc_id": 1,
                "file_name": 1,
                "file_type": 1,
                "source_type": 1,
                "tags": 1,
                "metadata": 1,
                "created_at": 1,
                "updated_at": 1,
                "status": 1,
            },
        )
        .sort("updated_at", -1)
        .limit(limit)
    )

    results = []

    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)

    return results


def get_all_active_chunks(
    source_type: Optional[str] = None,
    limit_documents: int = 100,
) -> List[Dict[str, Any]]:
    """
    Devuelve chunks activos para usarlos con document_retriever.py.
    """
    col = get_technical_documents_collection()

    query: Dict[str, Any] = {
        "status": "active",
    }

    if source_type:
        query["source_type"] = source_type

    cursor = (
        col.find(
            query,
            {
                "_id": 0,
                "doc_id": 1,
                "file_name": 1,
                "source_type": 1,
                "chunks": 1,
            },
        )
        .sort("updated_at", -1)
        .limit(limit_documents)
    )

    all_chunks: List[Dict[str, Any]] = []

    for doc in cursor:
        file_name = doc.get("file_name", "")
        doc_id = doc.get("doc_id", "")
        source_type_value = doc.get("source_type", "")

        for chunk in doc.get("chunks", []):
            if not isinstance(chunk, dict):
                continue

            all_chunks.append({
                **chunk,
                "doc_id": doc_id,
                "source": chunk.get("source") or file_name,
                "source_type": source_type_value,
                "file_name": file_name,
            })

    return all_chunks


def deactivate_document(doc_id: str) -> Dict[str, Any]:
    """
    Desactiva un documento sin borrarlo físicamente.
    """
    col = get_technical_documents_collection()

    result = col.update_one(
        {"doc_id": doc_id},
        {
            "$set": {
                "status": "inactive",
                "updated_at": _now_utc(),
            }
        },
    )

    return {
        "ok": result.modified_count > 0,
        "doc_id": doc_id,
        "modified_count": result.modified_count,
    }


# ============================================================
# ÍNDICES
# ============================================================

def ensure_document_indexes() -> Dict[str, Any]:
    """
    Crea índices básicos para la colección technical_documents.
    """
    col = get_technical_documents_collection()

    created = []

    created.append(
        col.create_index(
            "doc_id",
            unique=True,
            name="idx_doc_id_unique",
        )
    )

    created.append(
        col.create_index(
            "file_name",
            name="idx_file_name",
        )
    )

    created.append(
        col.create_index(
            "source_type",
            name="idx_source_type",
        )
    )

    created.append(
        col.create_index(
            "status",
            name="idx_status",
        )
    )

    created.append(
        col.create_index(
            "updated_at",
            name="idx_updated_at",
        )
    )

    return {
        "ok": True,
        "collection": TECHNICAL_DOCUMENTS_COLLECTION,
        "indexes": created,
    }