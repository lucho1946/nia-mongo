# ============================================================
# retrieval/document_retriever.py
# ============================================================
# RESPONSABILIDAD:
# Retriever documental base para NIA.
#
# Este módulo pertenece a la futura capa documental/RAG.
#
# Objetivo:
# - Recibir una pregunta del usuario.
# - Recibir chunks generados por knowledge/file_reader.py.
# - Calcular relevancia textual simple.
# - Devolver los chunks más útiles.
#
# IMPORTANTE:
# Este módulo NO responde al usuario.
# Este módulo NO consulta catálogo de productos.
# Este módulo NO recomienda productos.
# Este módulo NO se conecta todavía al orquestador.
# Este módulo NO usa embeddings todavía.
#
# Regla de Don Andrés:
# - Catálogo MongoDB = fuente de verdad para productos.
# - Documentos técnicos = soporte para explicar, validar o complementar.
# ============================================================

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, List, Optional


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEFAULT_TOP_K = 5
MIN_SCORE = 0.01


# ============================================================
# STOPWORDS BÁSICAS EN ESPAÑOL
# ============================================================
# Estas palabras aportan poco a la búsqueda documental.
# No buscamos perfección todavía; solo una base estable.
# ============================================================

SPANISH_STOPWORDS = {
    "a",
    "al",
    "algo",
    "ante",
    "antes",
    "como",
    "con",
    "contra",
    "cual",
    "cuando",
    "de",
    "del",
    "desde",
    "donde",
    "el",
    "ella",
    "ellos",
    "en",
    "entre",
    "era",
    "es",
    "esa",
    "ese",
    "eso",
    "esta",
    "este",
    "esto",
    "estos",
    "fue",
    "ha",
    "hay",
    "la",
    "las",
    "le",
    "lo",
    "los",
    "mas",
    "más",
    "me",
    "mi",
    "no",
    "o",
    "para",
    "pero",
    "por",
    "que",
    "qué",
    "se",
    "si",
    "sí",
    "sin",
    "sobre",
    "son",
    "su",
    "sus",
    "te",
    "tiene",
    "un",
    "una",
    "uno",
    "y",
}


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def normalize_text(text: Any) -> str:
    """
    Normaliza texto para comparación:
    - convierte a string
    - minúsculas
    - elimina acentos
    - limpia espacios
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def tokenize(text: Any) -> List[str]:
    """
    Convierte texto en tokens útiles.
    """
    normalized = normalize_text(text)

    raw_tokens = re.findall(r"[a-zA-Z0-9_\-\.]+", normalized)

    tokens = []

    for token in raw_tokens:
        token = token.strip("._-")

        if not token:
            continue

        if len(token) < 2:
            continue

        if token in SPANISH_STOPWORDS:
            continue

        tokens.append(token)

    # Quitamos duplicados manteniendo orden.
    cleaned_tokens = list(dict.fromkeys(tokens))

    return cleaned_tokens


def _safe_chunk_text(chunk: Dict[str, Any]) -> str:
    """
    Extrae texto seguro desde un chunk.
    """
    if not isinstance(chunk, dict):
        return ""

    return str(chunk.get("text") or "")


def _safe_source(chunk: Dict[str, Any]) -> str:
    """
    Extrae source seguro desde un chunk.
    """
    if not isinstance(chunk, dict):
        return ""

    return str(chunk.get("source") or chunk.get("file_name") or "")


# ============================================================
# SCORING DE RELEVANCIA
# ============================================================

def _term_frequency_score(query_tokens: List[str], chunk_tokens: List[str]) -> float:
    """
    Score simple por frecuencia de tokens de la pregunta dentro del chunk.
    """
    if not query_tokens or not chunk_tokens:
        return 0.0

    score = 0.0
    chunk_token_set = set(chunk_tokens)

    for token in query_tokens:
        if token in chunk_token_set:
            score += 1.0

    return score / max(len(query_tokens), 1)


def _partial_match_score(query_tokens: List[str], chunk_text: str) -> float:
    """
    Score adicional por coincidencias parciales.

    Ejemplo:
    - query: vision archivos
    - chunk: module_vision_archivos
    """
    if not query_tokens or not chunk_text:
        return 0.0

    chunk_text_norm = normalize_text(chunk_text)

    partial_hits = 0

    for token in query_tokens:
        if token in chunk_text_norm:
            partial_hits += 1

    return partial_hits / max(len(query_tokens), 1)


def _phrase_bonus(query: str, chunk_text: str) -> float:
    """
    Bonus si una frase relevante completa aparece dentro del chunk.
    """
    query_norm = normalize_text(query)
    chunk_norm = normalize_text(chunk_text)

    if not query_norm or not chunk_norm:
        return 0.0

    if query_norm in chunk_norm:
        return 1.0

    return 0.0


def _source_bonus(query_tokens: List[str], source: str) -> float:
    """
    Bonus si la pregunta coincide con el nombre del archivo fuente.
    """
    if not query_tokens or not source:
        return 0.0

    source_norm = normalize_text(source)

    hits = 0

    for token in query_tokens:
        if token in source_norm:
            hits += 1

    return hits / max(len(query_tokens), 1)


def score_chunk(
    query: str,
    chunk: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calcula score de relevancia para un chunk.

    Retorna:
    {
        "score": ...,
        "debug": {...}
    }
    """
    chunk_text = _safe_chunk_text(chunk)
    source = _safe_source(chunk)

    query_tokens = tokenize(query)
    chunk_tokens = tokenize(chunk_text)

    tf_score = _term_frequency_score(query_tokens, chunk_tokens)
    partial_score = _partial_match_score(query_tokens, chunk_text)
    phrase_score = _phrase_bonus(query, chunk_text)
    source_score = _source_bonus(query_tokens, source)

    # Score ponderado simple.
    # Más adelante esto puede evolucionar a embeddings.
    final_score = (
        (tf_score * 0.45)
        + (partial_score * 0.30)
        + (phrase_score * 0.15)
        + (source_score * 0.10)
    )

    return {
        "score": round(final_score, 4),
        "debug": {
            "query_tokens": query_tokens,
            "tf_score": round(tf_score, 4),
            "partial_score": round(partial_score, 4),
            "phrase_score": round(phrase_score, 4),
            "source_score": round(source_score, 4),
        },
    }


# ============================================================
# RETRIEVAL PRINCIPAL
# ============================================================

def retrieve_document_chunks(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> Dict[str, Any]:
    """
    Busca los chunks más relevantes para una pregunta.

    Parámetros:
    - query: pregunta o búsqueda del usuario.
    - chunks: lista de chunks generados por file_reader.py.
    - top_k: cantidad máxima de resultados.
    - min_score: score mínimo para aceptar resultados.

    Retorna una estructura estándar.
    """
    if not query or not str(query).strip():
        return {
            "ok": False,
            "query": query,
            "results": [],
            "metadata": {
                "total_chunks": len(chunks or []),
                "returned": 0,
            },
            "errors": ["La consulta está vacía."],
        }

    if not isinstance(chunks, list):
        return {
            "ok": False,
            "query": query,
            "results": [],
            "metadata": {
                "total_chunks": 0,
                "returned": 0,
            },
            "errors": ["Los chunks deben venir en una lista."],
        }

    if top_k <= 0:
        top_k = DEFAULT_TOP_K

    scored_results = []

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue

        score_data = score_chunk(query=query, chunk=chunk)
        score = score_data["score"]

        if score < min_score:
            continue

        result = {
            "chunk_id": chunk.get("chunk_id"),
            "source": _safe_source(chunk),
            "text": _safe_chunk_text(chunk),
            "score": score,
            "debug": score_data.get("debug", {}),
            "metadata": {
                "start_char": chunk.get("start_char"),
                "end_char": chunk.get("end_char"),
                "chars": chunk.get("chars"),
            },
        }

        scored_results.append(result)

    scored_results.sort(
        key=lambda item: item.get("score", 0.0),
        reverse=True,
    )

    selected_results = scored_results[:top_k]

    return {
        "ok": True,
        "query": query,
        "results": selected_results,
        "metadata": {
            "total_chunks": len(chunks),
            "matched_chunks": len(scored_results),
            "returned": len(selected_results),
            "top_k": top_k,
            "min_score": min_score,
        },
        "errors": [],
    }


def retrieve_from_file_result(
    query: str,
    file_result: Dict[str, Any],
    top_k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> Dict[str, Any]:
    """
    Ejecuta retrieval sobre el resultado de read_knowledge_file().
    """
    if not isinstance(file_result, dict):
        return {
            "ok": False,
            "query": query,
            "results": [],
            "metadata": {
                "total_chunks": 0,
                "returned": 0,
            },
            "errors": ["file_result debe ser un diccionario."],
        }

    chunks = file_result.get("chunks", [])

    return retrieve_document_chunks(
        query=query,
        chunks=chunks,
        top_k=top_k,
        min_score=min_score,
    )


def retrieve_from_folder_result(
    query: str,
    folder_result: Dict[str, Any],
    top_k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> Dict[str, Any]:
    """
    Ejecuta retrieval sobre el resultado de read_knowledge_folder().

    Junta todos los chunks de todos los archivos leídos.
    """
    if not isinstance(folder_result, dict):
        return {
            "ok": False,
            "query": query,
            "results": [],
            "metadata": {
                "total_chunks": 0,
                "returned": 0,
            },
            "errors": ["folder_result debe ser un diccionario."],
        }

    files = folder_result.get("files", [])

    all_chunks: List[Dict[str, Any]] = []

    for file_item in files:
        if not isinstance(file_item, dict):
            continue

        file_name = file_item.get("file_name", "")

        for chunk in file_item.get("chunks", []):
            if not isinstance(chunk, dict):
                continue

            # Aseguramos que el chunk tenga fuente.
            enriched_chunk = {
                **chunk,
                "source": chunk.get("source") or file_name,
            }

            all_chunks.append(enriched_chunk)

    return retrieve_document_chunks(
        query=query,
        chunks=all_chunks,
        top_k=top_k,
        min_score=min_score,
    )


# ============================================================
# CONTEXTO DOCUMENTAL PARA FUTURO ORQUESTADOR
# ============================================================

def build_document_context(
    retrieval_result: Dict[str, Any],
    max_chars: int = 3000,
) -> Dict[str, Any]:
    """
    Construye un contexto documental compacto.

    Esto todavía NO se conecta al orquestador, pero deja listo
    el formato que más adelante podremos pasarle al cerebro.

    Retorna:
    {
        "context_text": "...",
        "sources": [...],
        "chunk_count": ...
    }
    """
    if not isinstance(retrieval_result, dict):
        return {
            "context_text": "",
            "sources": [],
            "chunk_count": 0,
        }

    results = retrieval_result.get("results", [])

    context_parts = []
    sources = []
    current_chars = 0

    for item in results:
        if not isinstance(item, dict):
            continue

        source = item.get("source") or ""
        chunk_id = item.get("chunk_id") or ""
        text = item.get("text") or ""

        header = f"[FUENTE: {source} | CHUNK: {chunk_id}]"
        block = f"{header}\n{text}".strip()

        remaining_chars = max_chars - current_chars

        if remaining_chars <= 0:
            break

        # Si el bloque completo no cabe, guardamos una versión recortada.
        # Esto evita que el contexto documental quede vacío cuando el
        # primer chunk es más largo que max_chars.
        if len(block) > remaining_chars:
            block = block[:remaining_chars].rstrip()

        context_parts.append(block)
        current_chars += len(block)

        if source and source not in sources:
            sources.append(source)

    return {
        "context_text": "\n\n".join(context_parts),
        "sources": sources,
        "chunk_count": len(context_parts),
    }


# ============================================================
# DEBUG / EXPLICACIÓN
# ============================================================

def explain_retrieval(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int = DEFAULT_TOP_K,
) -> Dict[str, Any]:
    """
    Devuelve una explicación del retrieval para depuración.
    """
    result = retrieve_document_chunks(
        query=query,
        chunks=chunks,
        top_k=top_k,
    )

    return {
        "query": query,
        "metadata": result.get("metadata", {}),
        "results_debug": [
            {
                "chunk_id": item.get("chunk_id"),
                "source": item.get("source"),
                "score": item.get("score"),
                "debug": item.get("debug"),
                "preview": (item.get("text") or "")[:300],
            }
            for item in result.get("results", [])
        ],
    }