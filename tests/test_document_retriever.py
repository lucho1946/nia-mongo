# ============================================================
# test_document_retriever.py
# ============================================================
# Prueba aislada del retriever documental de NIA.
#
# Este test NO toca:
# - orquestador
# - memoria conversacional
# - catÃ¡logo de productos
# - MongoDB
# - Azure
#
# Solo valida:
# - leer documentos con file_reader.py
# - generar chunks
# - buscar chunks relevantes con document_retriever.py
# ============================================================

from knowledge.file_reader import read_knowledge_folder
from retrieval.document_retriever import (
    retrieve_from_folder_result,
    build_document_context,
    explain_retrieval,
)


# ============================================================
# CONFIGURACIÃ“N DE PRUEBA
# ============================================================

FOLDER_TO_TEST = "knowledge/nia_os"

TEST_QUERIES = [
    "quÃ© hace module_vision_archivos",
    "reglas para no inventar productos",
    "cÃ³mo consultar productos en la API",
    "memoria contextual de la conversaciÃ³n",
    "cotizaciÃ³n precio disponibilidad",
]


# ============================================================
# IMPRESIÃ“N DE RESULTADOS
# ============================================================

def print_retrieval_result(query: str, result: dict) -> None:
    """
    Imprime resultado legible del retrieval.
    """
    print("\n" + "=" * 70)
    print("NIA DOCUMENT RETRIEVER TEST")
    print("=" * 70)

    print("QUERY:", query)
    print("OK:", result.get("ok"))

    metadata = result.get("metadata", {}) or {}

    print("Total chunks:", metadata.get("total_chunks"))
    print("Matched chunks:", metadata.get("matched_chunks"))
    print("Returned:", metadata.get("returned"))

    if result.get("errors"):
        print("\nERRORES:")
        for error in result.get("errors", []):
            print("-", error)

    results = result.get("results", [])

    print("\nRESULTADOS:")
    for index, item in enumerate(results, start=1):
        text = item.get("text", "") or ""
        preview = text[:500].replace("\n", " ")

        print("-" * 70)
        print(f"{index}. Source: {item.get('source')}")
        print(f"   Chunk: {item.get('chunk_id')}")
        print(f"   Score: {item.get('score')}")
        print(f"   Preview: {preview}")

    context = build_document_context(result, max_chars=1200)

    print("\nCONTEXTO DOCUMENTAL COMPACTO:")
    print("-" * 70)
    print("Sources:", context.get("sources"))
    print("Chunk count:", context.get("chunk_count"))
    print("Context preview:")
    print((context.get("context_text") or "")[:1200])

    print("\nFIN QUERY")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta prueba documental completa.
    """
    print("\nLeyendo carpeta de conocimiento...")
    folder_result = read_knowledge_folder(FOLDER_TO_TEST)

    print("OK lectura carpeta:", folder_result.get("ok"))
    print("Resumen:", folder_result.get("summary"))

    if not folder_result.get("ok"):
        print("Errores de lectura:")
        for error in folder_result.get("errors", []):
            print("-", error)
        return

    for query in TEST_QUERIES:
        result = retrieve_from_folder_result(
            query=query,
            folder_result=folder_result,
            top_k=3,
            min_score=0.01,
        )

        print_retrieval_result(query, result)

    # Debug adicional sobre todos los chunks.
    all_chunks = []

    for file_item in folder_result.get("files", []):
        file_name = file_item.get("file_name", "")

        for chunk in file_item.get("chunks", []):
            all_chunks.append({
                **chunk,
                "source": chunk.get("source") or file_name,
            })

    debug = explain_retrieval(
        query="module_vision_archivos",
        chunks=all_chunks,
        top_k=3,
    )

    print("\n" + "=" * 70)
    print("DEBUG FINAL")
    print("=" * 70)
    print(debug)
    print("=" * 70)


if __name__ == "__main__":
    main()

