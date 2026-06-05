# ============================================================
# retrieval/industrial_knowledge_retriever.py
# ============================================================
# Responsabilidad:
# Buscar fragmentos relevantes dentro de los libros industriales
# procesados para RAG.
#
# Esta capa NO reemplaza:
# - MongoDB/products_catalog
# - services/search.py
# - services.catalog_line_matcher
# - OpenAI
#
# Esta capa solo entrega contexto técnico industrial para que NIA
# entienda mejor la necesidad del cliente antes de buscar productos.
#
# Reglas:
# - No recomienda productos.
# - No inventa productos.
# - No confirma precios, stock ni disponibilidad.
# - No clasifica por familias manuales.
# - No usa marcas manuales.
# - No contiene listas técnicas hardcodeadas.
# - Solo consulta conocimiento técnico desde libros.
#
# Diseño:
# - Carga book_rag_ready_all.jsonl.
# - Repara mojibake común.
# - Normaliza texto.
# - Elimina conectores gramaticales mínimos.
# - Calcula relevancia por:
#   1. coincidencia de frases;
#   2. coincidencia de tokens útiles;
#   3. cobertura de consulta;
#   4. pesos por campo documental.
#
# Versión:
# industrial_knowledge_retriever_v1.1_clean
# ============================================================

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Set


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BOOK_RAG_PATH = (
    PROJECT_ROOT
    / "knowledge"
    / "industrial_books"
    / "book_rag_ready_all.jsonl"
)

INDUSTRIAL_KNOWLEDGE_RETRIEVER_VERSION = "industrial_knowledge_retriever_v1.1_clean"


# ============================================================
# STOPWORDS GRAMATICALES MÍNIMAS
# ============================================================
# Esto NO es una lista técnica.
# Esto NO contiene productos.
# Esto NO contiene familias.
# Esto NO contiene marcas.
#
# Solo se eliminan conectores de idioma para que palabras como
# "de", "del", "la", "el", "para" no afecten el ranking.
# ============================================================

GRAMMAR_STOPWORDS: Set[str] = {
    # Español básico
    "a",
    "al",
    "ante",
    "bajo",
    "con",
    "contra",
    "de",
    "del",
    "desde",
    "durante",
    "e",
    "el",
    "en",
    "entre",
    "hacia",
    "hasta",
    "la",
    "las",
    "lo",
    "los",
    "o",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "sobre",
    "u",
    "un",
    "una",
    "unas",
    "uno",
    "unos",
    "y",

    # Inglés básico, por el libro de Kuphaldt
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


# ============================================================
# UTILIDADES BASE
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte cualquier valor a string seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def _clean_control_chars(text: Any) -> str:
    """
    Elimina caracteres de control que vienen del procesamiento PDF.
    """
    raw = _safe_str(text)

    if not raw:
        return ""

    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned.strip()


def _repair_mojibake(text: Any) -> str:
    """
    Repara mojibake típico:
    'InstrumentaciÃ³n' -> 'Instrumentación'

    Si no hay señales de mojibake o falla la reparación,
    devuelve el texto limpio original.
    """
    raw = _clean_control_chars(text)

    if not raw:
        return ""

    has_mojibake_signal = (
        "Ã" in raw
        or "Â" in raw
        or "â" in raw
    )

    if not has_mojibake_signal:
        return raw

    try:
        repaired = raw.encode("latin1", errors="ignore").decode(
            "utf-8",
            errors="ignore",
        )
        return _clean_control_chars(repaired)
    except Exception:
        return raw


def _normalize(text: Any) -> str:
    """
    Normaliza texto para comparación:
    - repara mojibake;
    - convierte a minúsculas;
    - elimina tildes;
    - deja letras, números y espacios.
    """
    repaired = _repair_mojibake(text).lower()

    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", repaired)
        if not unicodedata.combining(char)
    )

    cleaned = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokenize(text: Any) -> List[str]:
    """
    Tokeniza texto normalizado eliminando únicamente:
    - tokens muy cortos;
    - conectores gramaticales mínimos.

    No elimina términos técnicos.
    """
    normalized = _normalize(text)

    if not normalized:
        return []

    result: List[str] = []

    for token in normalized.split():
        if len(token) < 3:
            continue

        if token in GRAMMAR_STOPWORDS:
            continue

        result.append(token)

    return result


def _unique_tokens(tokens: List[str]) -> List[str]:
    """
    Mantiene tokens únicos conservando el orden.
    """
    seen = set()
    result: List[str] = []

    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append(token)

    return result


def _build_query_phrases(tokens: List[str]) -> List[str]:
    """
    Construye frases de 2 y 3 tokens desde la consulta ya limpia.

    Ejemplo:
    ["velocidad", "aire", "ductos"]
    ->
    ["velocidad aire", "aire ductos", "velocidad aire ductos"]

    Las frases ayudan a identificar coincidencias más fuertes
    que palabras sueltas.
    """
    phrases: List[str] = []

    if len(tokens) < 2:
        return phrases

    for index in range(len(tokens) - 1):
        phrases.append(f"{tokens[index]} {tokens[index + 1]}")

    if len(tokens) >= 3:
        for index in range(len(tokens) - 2):
            phrases.append(
                f"{tokens[index]} {tokens[index + 1]} {tokens[index + 2]}"
            )

    return _unique_tokens(phrases)


def _token_text(text: Any) -> str:
    """
    Convierte un texto en una cadena normalizada sin conectores.

    Esto permite buscar frases como:
    'velocidad aire'

    aunque el texto original diga:
    'velocidad del aire'
    """
    return " ".join(_tokenize(text))


# ============================================================
# CARGA JSONL
# ============================================================

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """
    Carga registros JSONL de libros industriales.

    Si una línea falla, se ignora para no tumbar el backend completo.
    """
    if not path.exists():
        return []

    records: List[Dict[str, Any]] = []

    with path.open("r", encoding="utf-8", errors="ignore") as file:
        for line_number, line in enumerate(file, start=1):
            raw = line.strip()

            if not raw:
                continue

            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(item, dict):
                continue

            item["_line_number"] = line_number
            records.append(item)

    return records


@lru_cache(maxsize=1)
def load_industrial_book_records() -> List[Dict[str, Any]]:
    """
    Carga en memoria los fragmentos RAG-ready.

    Se usa caché para evitar leer el JSONL completo en cada consulta.
    """
    return _load_jsonl(DEFAULT_BOOK_RAG_PATH)


# ============================================================
# EXTRACCIÓN DE CAMPOS
# ============================================================

def _metadata_text(record: Dict[str, Any]) -> str:
    """
    Extrae texto útil desde metadata.

    No interpreta los términos. Solo usa lo que ya viene
    procesado en el archivo RAG-ready.
    """
    metadata = record.get("metadata") or {}

    parts = [
        " ".join(metadata.get("technical_terms") or []),
        " ".join(metadata.get("signals") or []),
        " ".join(metadata.get("units") or []),
        " ".join(metadata.get("formulas") or []),
    ]

    return " ".join(_repair_mojibake(part) for part in parts if part)


def _high_priority_text(record: Dict[str, Any]) -> str:
    """
    Campos de alta prioridad documental.

    Estos campos indican mejor de qué trata el fragmento:
    título, capítulo, sección, dominio, tipo de contenido y metadata.
    """
    parts = [
        record.get("title"),
        record.get("chapter"),
        record.get("section"),
        record.get("domain"),
        record.get("content_type"),
        _metadata_text(record),
    ]

    return " ".join(_repair_mojibake(part) for part in parts if part)


def _main_text(record: Dict[str, Any]) -> str:
    """
    Texto principal del fragmento.
    """
    return _repair_mojibake(record.get("text"))


def _search_text(record: Dict[str, Any]) -> str:
    """
    Texto ampliado preparado para búsqueda.
    """
    return _repair_mojibake(record.get("search_text"))


def _full_record_text(record: Dict[str, Any]) -> str:
    """
    Texto completo usado como respaldo.
    """
    parts = [
        _high_priority_text(record),
        _main_text(record),
        _search_text(record),
    ]

    return " ".join(part for part in parts if part)


# ============================================================
# INDEXACIÓN LIGERA EN MEMORIA
# ============================================================

@lru_cache(maxsize=1)
def load_indexed_industrial_book_records() -> List[Dict[str, Any]]:
    """
    Crea una representación indexada de los registros.

    Esto evita normalizar y tokenizar todos los campos en cada búsqueda.
    """
    indexed_records: List[Dict[str, Any]] = []

    for record in load_industrial_book_records():
        high_text = _high_priority_text(record)
        main_text = _main_text(record)
        search_text = _search_text(record)
        full_text = _full_record_text(record)

        indexed_records.append(
            {
                "record": record,

                # Textos normalizados completos.
                "normalized_high_text": _normalize(high_text),
                "normalized_main_text": _normalize(main_text),
                "normalized_search_text": _normalize(search_text),
                "normalized_full_text": _normalize(full_text),

                # Textos tokenizados sin conectores para phrase matching.
                "token_high_text": _token_text(high_text),
                "token_main_text": _token_text(main_text),
                "token_search_text": _token_text(search_text),
                "token_full_text": _token_text(full_text),

                # Sets de tokens para coincidencia rápida.
                "high_tokens": set(_tokenize(high_text)),
                "main_tokens": set(_tokenize(main_text)),
                "search_tokens": set(_tokenize(search_text)),
                "full_tokens": set(_tokenize(full_text)),
            }
        )

    return indexed_records


# ============================================================
# SCORING GENÉRICO
# ============================================================

def _score_token_matches(
    query_tokens: List[str],
    indexed_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calcula score por coincidencia de tokens con pesos por campo.

    No hay pesos por producto, marca, familia ni término técnico manual.
    Solo se pondera en qué campo documental apareció el token.
    """
    matched_terms: List[str] = []
    score = 0.0

    high_tokens = indexed_record["high_tokens"]
    main_tokens = indexed_record["main_tokens"]
    search_tokens = indexed_record["search_tokens"]

    for token in query_tokens:
        token_score = 0.0

        if token in high_tokens:
            token_score += 7.0

        if token in main_tokens:
            token_score += 4.0

        if token in search_tokens:
            token_score += 2.0

        if token_score > 0:
            matched_terms.append(token)
            score += token_score

    return {
        "score": score,
        "matched_terms": _unique_tokens(matched_terms),
    }


def _score_phrase_matches(
    query_phrases: List[str],
    indexed_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calcula score por coincidencia de frases.

    Usamos los textos tokenizados sin conectores para que una frase como
    'velocidad aire' pueda coincidir con 'velocidad del aire'.
    """
    matched_phrases: List[str] = []
    score = 0.0

    high_text = indexed_record["token_high_text"]
    main_text = indexed_record["token_main_text"]
    search_text = indexed_record["token_search_text"]

    for phrase in query_phrases:
        phrase_score = 0.0
        phrase_length = len(phrase.split())

        if phrase in high_text:
            phrase_score += 18.0 if phrase_length >= 3 else 12.0

        if phrase in main_text:
            phrase_score += 12.0 if phrase_length >= 3 else 8.0

        if phrase in search_text:
            phrase_score += 8.0 if phrase_length >= 3 else 5.0

        if phrase_score > 0:
            matched_phrases.append(phrase)
            score += phrase_score

    return {
        "score": score,
        "matched_phrases": _unique_tokens(matched_phrases),
    }


def _coverage_data(
    query_tokens: List[str],
    matched_terms: List[str],
    matched_phrases: List[str],
) -> Dict[str, Any]:
    """
    Calcula cobertura de consulta.

    La cobertura evita que un resultado suba solo por coincidir
    con una palabra aislada.
    """
    if not query_tokens:
        return {
            "coverage": 0.0,
            "bonus": 0.0,
            "penalty": 0.0,
        }

    query_set = set(query_tokens)
    matched_set = set(matched_terms)

    coverage = len(matched_set) / max(len(query_set), 1)

    bonus = 0.0
    penalty = 0.0

    if coverage >= 0.80:
        bonus += 14.0
    elif coverage >= 0.60:
        bonus += 9.0
    elif coverage >= 0.40:
        bonus += 4.0
    else:
        penalty += 10.0

    if matched_phrases:
        bonus += min(len(matched_phrases) * 5.0, 20.0)

    return {
        "coverage": round(coverage, 4),
        "bonus": bonus,
        "penalty": penalty,
    }


def _weak_evidence_penalty(
    matched_terms: List[str],
    matched_phrases: List[str],
) -> float:
    """
    Penaliza evidencia débil.

    Si solo hay 1 token coincidente y ninguna frase, el fragmento
    probablemente no es suficiente para apoyar a NIA.
    """
    if matched_phrases:
        return 0.0

    unique_matches = set(matched_terms)

    if len(unique_matches) == 0:
        return 0.0

    if len(unique_matches) == 1:
        return 12.0

    if len(unique_matches) == 2:
        return 5.0

    return 0.0


def _score_record(
    query_tokens: List[str],
    query_phrases: List[str],
    indexed_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calcula score final entre consulta y fragmento.
    """
    token_score_data = _score_token_matches(
        query_tokens=query_tokens,
        indexed_record=indexed_record,
    )

    phrase_score_data = _score_phrase_matches(
        query_phrases=query_phrases,
        indexed_record=indexed_record,
    )

    matched_terms = token_score_data["matched_terms"]
    matched_phrases = phrase_score_data["matched_phrases"]

    coverage = _coverage_data(
        query_tokens=query_tokens,
        matched_terms=matched_terms,
        matched_phrases=matched_phrases,
    )

    weak_penalty = _weak_evidence_penalty(
        matched_terms=matched_terms,
        matched_phrases=matched_phrases,
    )

    score = (
        token_score_data["score"]
        + phrase_score_data["score"]
        + coverage["bonus"]
        - coverage["penalty"]
        - weak_penalty
    )

    score = max(score, 0.0)

    return {
        "score": round(score, 2),
        "matched_terms": matched_terms,
        "matched_phrases": matched_phrases,
        "coverage": coverage["coverage"],
        "debug_score": {
            "token_score": round(token_score_data["score"], 2),
            "phrase_score": round(phrase_score_data["score"], 2),
            "coverage_bonus": round(coverage["bonus"], 2),
            "coverage_penalty": round(coverage["penalty"], 2),
            "weak_evidence_penalty": round(weak_penalty, 2),
        },
    }


# ============================================================
# FORMATO DE SALIDA
# ============================================================

def _public_record(
    record: Dict[str, Any],
    score_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Devuelve un resultado seguro para consumo interno de NIA.
    """
    metadata = record.get("metadata") or {}

    text = _repair_mojibake(record.get("text"))
    search_text = _repair_mojibake(record.get("search_text"))

    excerpt = text[:900].strip()

    return {
        "id": record.get("id"),
        "source_type": record.get("source_type"),
        "source_id": record.get("source_id"),
        "title": _repair_mojibake(record.get("title")),
        "author": _repair_mojibake(record.get("author")),
        "edition": _repair_mojibake(record.get("edition")),
        "language": record.get("language"),
        "page": record.get("page"),
        "chapter": _repair_mojibake(record.get("chapter")),
        "section": _repair_mojibake(record.get("section")),
        "domain": _repair_mojibake(record.get("domain")),
        "content_type": _repair_mojibake(record.get("content_type")),
        "excerpt": excerpt,
        "score": score_data.get("score", 0.0),
        "matched_terms": score_data.get("matched_terms", []),
        "matched_phrases": score_data.get("matched_phrases", []),
        "coverage": score_data.get("coverage", 0.0),
        "metadata": {
            "tokens_aprox": metadata.get("tokens_aprox"),
            "technical_terms": metadata.get("technical_terms") or [],
            "signals": metadata.get("signals") or [],
            "units": metadata.get("units") or [],
            "formulas": metadata.get("formulas") or [],
            "hash": metadata.get("hash"),
        },
        "_debug": {
            "line_number": record.get("_line_number"),
            "search_text_preview": search_text[:300],
            "debug_score": score_data.get("debug_score", {}),
        },
    }


# ============================================================
# API INTERNA
# ============================================================

def search_industrial_knowledge(
    query: str,
    *,
    max_results: int = 5,
    min_score: float = 18.0,
) -> Dict[str, Any]:
    """
    Busca conocimiento técnico industrial relevante.

    Args:
        query:
            Consulta técnica del usuario o normalized_query.
        max_results:
            Número máximo de fragmentos a devolver.
        min_score:
            Score mínimo para considerar un fragmento relevante.

    Returns:
        dict con metadata de búsqueda y resultados.
    """
    raw_query = _safe_str(query)

    query_tokens = _unique_tokens(_tokenize(raw_query))
    query_phrases = _build_query_phrases(query_tokens)

    total_records = len(load_industrial_book_records())

    if not query_tokens:
        return {
            "ok": True,
            "version": INDUSTRIAL_KNOWLEDGE_RETRIEVER_VERSION,
            "query": raw_query,
            "normalized_query": "",
            "query_tokens": [],
            "query_phrases": [],
            "source_path": str(DEFAULT_BOOK_RAG_PATH),
            "total_records": total_records,
            "result_count": 0,
            "results": [],
            "reason": "empty_query",
        }

    indexed_records = load_indexed_industrial_book_records()

    scored_results: List[Dict[str, Any]] = []

    for indexed_record in indexed_records:
        score_data = _score_record(
            query_tokens=query_tokens,
            query_phrases=query_phrases,
            indexed_record=indexed_record,
        )

        if score_data["score"] < min_score:
            continue

        scored_results.append(
            _public_record(
                record=indexed_record["record"],
                score_data=score_data,
            )
        )

    scored_results.sort(
        key=lambda item: (
            item.get("score", 0.0),
            item.get("coverage", 0.0),
            len(item.get("matched_phrases", [])),
        ),
        reverse=True,
    )

    limited_results = scored_results[:max_results]

    return {
        "ok": True,
        "version": INDUSTRIAL_KNOWLEDGE_RETRIEVER_VERSION,
        "query": raw_query,
        "normalized_query": _normalize(raw_query),
        "query_tokens": query_tokens,
        "query_phrases": query_phrases,
        "source_path": str(DEFAULT_BOOK_RAG_PATH),
        "total_records": total_records,
        "result_count": len(limited_results),
        "results": limited_results,
        "reason": "ok",
    }


def build_industrial_context_for_prompt(
    query: str,
    *,
    max_results: int = 3,
    max_chars: int = 2500,
) -> Dict[str, Any]:
    """
    Construye un contexto compacto para enviar a OpenAI más adelante.

    Este contexto todavía no recomienda productos.
    Solo aporta fragmentos técnicos relevantes de libros industriales.
    """
    search_result = search_industrial_knowledge(
        query=query,
        max_results=max_results,
    )

    fragments: List[str] = []

    for index, item in enumerate(search_result.get("results", []), start=1):
        fragment = (
            f"[Fragmento {index}]\n"
            f"Fuente: {item.get('title')} | Autor: {item.get('author')} | Página: {item.get('page')}\n"
            f"Dominio: {item.get('domain')} | Tipo: {item.get('content_type')}\n"
            f"Coincidencias: {', '.join(item.get('matched_terms', []))}\n"
            f"Frases: {', '.join(item.get('matched_phrases', []))}\n"
            f"Texto: {item.get('excerpt')}\n"
        )

        fragments.append(fragment)

    context = "\n\n".join(fragments).strip()

    if len(context) > max_chars:
        context = context[:max_chars].strip()

    return {
        "ok": search_result.get("ok", False),
        "version": INDUSTRIAL_KNOWLEDGE_RETRIEVER_VERSION,
        "query": query,
        "result_count": search_result.get("result_count", 0),
        "context": context,
        "results": search_result.get("results", []),
    }