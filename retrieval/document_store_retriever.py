# ============================================================
# retrieval/document_store_retriever.py
# ============================================================
# RESPONSABILIDAD:
# Retriever documental usando documentos ya guardados en MongoDB.
#
# Este módulo conecta:
# - services/document_store.py
# - retrieval/document_retriever.py
#
# Flujo:
# 1. Consulta chunks activos desde MongoDB technical_documents.
# 2. Ejecuta búsqueda textual sobre esos chunks.
# 3. Construye contexto documental compacto.
#
# IMPORTANTE:
# Este módulo NO recomienda productos.
# Este módulo NO consulta products_catalog.
# Este módulo NO responde directamente al usuario.
# Este módulo NO se conecta todavía al orquestador.
#
# Regla de Don Andrés:
# - products_catalog = fuente de verdad para productos.
# - technical_documents = soporte técnico/documental.
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services.document_store import get_all_active_chunks
from retrieval.document_retriever import (
    retrieve_document_chunks,
    build_document_context,
)

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEFAULT_SOURCE_TYPE = None
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.01
DEFAULT_MAX_CONTEXT_CHARS = 3000


# ============================================================
# RETRIEVAL DESDE MONGODB
# ============================================================

def retrieve_from_document_store(
    query: str,
    source_type: Optional[str] = DEFAULT_SOURCE_TYPE,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    limit_documents: int = 100,
) -> Dict[str, Any]:
    """
    Busca chunks relevantes directamente desde MongoDB.

    Parámetros:
    - query: pregunta o necesidad documental.
    - source_type: tipo de fuente, por ejemplo "nia_os", "manual", "ficha_tecnica".
    - top_k: cantidad máxima de chunks devueltos.
    - min_score: score mínimo.
    - limit_documents: máximo de documentos activos a consultar.

    Retorna:
    {
        "ok": True,
        "query": "...",
        "results": [...],
        "metadata": {...},
        "errors": []
    }
    """
    if not query or not str(query).strip():
        return {
            "ok": False,
            "query": query,
            "results": [],
            "metadata": {
                "source_type": source_type,
                "total_chunks": 0,
                "returned": 0,
            },
            "errors": ["La consulta está vacía."],
        }

    try:
        chunks = get_all_active_chunks(
            source_type=source_type,
            limit_documents=limit_documents,
        )

        retrieval_result = retrieve_document_chunks(
            query=query,
            chunks=chunks,
            top_k=top_k,
            min_score=min_score,
        )

        metadata = retrieval_result.get("metadata", {}) or {}

        retrieval_result["metadata"] = {
            **metadata,
            "source_type": source_type,
            "chunks_loaded_from_store": len(chunks),
            "limit_documents": limit_documents,
        }

        return retrieval_result

    except Exception as error:
        logger.error(f"Error en retrieve_from_document_store: {error}")

        return {
            "ok": False,
            "query": query,
            "results": [],
            "metadata": {
                "source_type": source_type,
                "total_chunks": 0,
                "returned": 0,
            },
            "errors": [str(error)],
        }


def build_context_from_document_store(
    query: str,
    source_type: Optional[str] = DEFAULT_SOURCE_TYPE,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    limit_documents: int = 100,
) -> Dict[str, Any]:
    """
    Ejecuta retrieval desde MongoDB y construye contexto documental compacto.

    Esta función deja listo el formato que más adelante podrá usar
    el orquestador de NIA.

    Retorna:
    {
        "ok": True,
        "query": "...",
        "context_text": "...",
        "sources": [...],
        "chunk_count": 3,
        "retrieval": {...},
        "errors": []
    }
    """
    retrieval_result = retrieve_from_document_store(
        query=query,
        source_type=source_type,
        top_k=top_k,
        min_score=min_score,
        limit_documents=limit_documents,
    )

    if not retrieval_result.get("ok"):
        return {
            "ok": False,
            "query": query,
            "context_text": "",
            "sources": [],
            "chunk_count": 0,
            "retrieval": retrieval_result,
            "errors": retrieval_result.get("errors", []),
        }

    context = build_document_context(
        retrieval_result=retrieval_result,
        max_chars=max_chars,
    )

    return {
        "ok": True,
        "query": query,
        "context_text": context.get("context_text", ""),
        "sources": context.get("sources", []),
        "chunk_count": context.get("chunk_count", 0),
        "retrieval": retrieval_result,
        "errors": [],
    }


# ============================================================
# FUNCIÓN DE SOPORTE PARA FUTURO ORQUESTADOR
# ============================================================

def get_documental_support_context(
    query: str,
    source_type: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> Dict[str, Any]:
    """
    Función semántica pensada para el futuro orquestador.

    Todavía NO se usa en nia_orchestrator.py, pero deja claro
    el contrato que después podremos conectar.

    Uso futuro esperado:
    document_context = get_documental_support_context(
        query=search_query,
        source_type="nia_os"
    )

    Retorna contexto documental compacto con fuentes.
    """
    return build_context_from_document_store(
        query=query,
        source_type=source_type,
        top_k=DEFAULT_TOP_K,
        min_score=DEFAULT_MIN_SCORE,
        max_chars=max_chars,
    )


# ============================================================
# DEBUG
# ============================================================

def explain_document_store_retrieval(
    query: str,
    source_type: Optional[str] = DEFAULT_SOURCE_TYPE,
    top_k: int = DEFAULT_TOP_K,
) -> Dict[str, Any]:
    """
    Devuelve una explicación compacta del retrieval desde MongoDB.
    """
    result = retrieve_from_document_store(
        query=query,
        source_type=source_type,
        top_k=top_k,
        min_score=DEFAULT_MIN_SCORE,
    )

    return {
        "query": query,
        "ok": result.get("ok"),
        "metadata": result.get("metadata", {}),
        "errors": result.get("errors", []),
        "results_debug": [
            {
                "source": item.get("source"),
                "chunk_id": item.get("chunk_id"),
                "score": item.get("score"),
                "preview": (item.get("text") or "")[:300],
                "debug": item.get("debug", {}),
            }
            for item in result.get("results", [])
        ],
    }