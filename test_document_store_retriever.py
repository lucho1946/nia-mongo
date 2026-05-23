# ============================================================
# test_document_store_retriever.py
# ============================================================
# Prueba aislada del retriever documental desde MongoDB.
#
# Este test valida:
# - cargar .env
# - leer chunks desde technical_documents
# - buscar chunks relevantes
# - construir contexto documental compacto
#
# NO toca:
# - nia_orchestrator.py
# - products_catalog
# - flujo conversacional de producción
# ============================================================

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

from retrieval.document_store_retriever import (
    retrieve_from_document_store,
    build_context_from_document_store,
    explain_document_store_retrieval,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

SOURCE_TYPE = "nia_os"

TEST_QUERIES = [
    "reglas para no inventar productos",
    "cómo consultar productos en la API",
    "qué hace module_vision_archivos",
    "memoria contextual de la conversación",
    "cotización precio disponibilidad",
]


# ============================================================
# VALIDACIÓN
# ============================================================

def validate_environment() -> bool:
    """
    Valida que exista MONGO_CONNECTION_STRING.
    """
    if not os.getenv("MONGO_CONNECTION_STRING"):
        print("ERROR: No se encontró MONGO_CONNECTION_STRING en el entorno.")
        print("Verifica tu archivo .env en la raíz del proyecto.")
        return False

    print("Variable MONGO_CONNECTION_STRING detectada correctamente.")
    return True


# ============================================================
# IMPRESIÓN
# ============================================================

def print_result(query: str, result: dict, context_result: dict) -> None:
    """
    Imprime resultado legible.
    """
    print("\n" + "=" * 70)
    print("NIA DOCUMENT STORE RETRIEVER TEST")
    print("=" * 70)

    print("QUERY:", query)
    print("Retrieval OK:", result.get("ok"))

    metadata = result.get("metadata", {}) or {}

    print("Chunks cargados desde store:", metadata.get("chunks_loaded_from_store"))
    print("Total chunks evaluados:", metadata.get("total_chunks"))
    print("Matched chunks:", metadata.get("matched_chunks"))
    print("Returned:", metadata.get("returned"))

    if result.get("errors"):
        print("\nERRORES:")
        for error in result.get("errors", []):
            print("-", error)

    print("\nRESULTADOS:")
    for index, item in enumerate(result.get("results", []), start=1):
        preview = (item.get("text") or "")[:350].replace("\n", " ")

        print("-" * 70)
        print(f"{index}. Source: {item.get('source')}")
        print(f"   Chunk: {item.get('chunk_id')}")
        print(f"   Score: {item.get('score')}")
        print(f"   Preview: {preview}")

    print("\nCONTEXTO DOCUMENTAL:")
    print("-" * 70)
    print("Context OK:", context_result.get("ok"))
    print("Sources:", context_result.get("sources"))
    print("Chunk count:", context_result.get("chunk_count"))
    print("Preview:")
    print((context_result.get("context_text") or "")[:1200])

    print("\nFIN QUERY")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta prueba completa.
    """
    print("\n" + "=" * 70)
    print("NIA DOCUMENT STORE RETRIEVER TEST")
    print("=" * 70)

    print("\n0. Validando entorno...")

    if not validate_environment():
        return

    for query in TEST_QUERIES:
        result = retrieve_from_document_store(
            query=query,
            source_type=SOURCE_TYPE,
            top_k=3,
            min_score=0.01,
            limit_documents=50,
        )

        context_result = build_context_from_document_store(
            query=query,
            source_type=SOURCE_TYPE,
            top_k=3,
            min_score=0.01,
            max_chars=1200,
            limit_documents=50,
        )

        print_result(
            query=query,
            result=result,
            context_result=context_result,
        )

    print("\n" + "=" * 70)
    print("DEBUG FINAL")
    print("=" * 70)

    debug = explain_document_store_retrieval(
        query="module_vision_archivos",
        source_type=SOURCE_TYPE,
        top_k=3,
    )

    print(debug)
    print("=" * 70)


if __name__ == "__main__":
    main()