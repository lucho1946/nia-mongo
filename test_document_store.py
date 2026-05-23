# ============================================================
# test_document_store.py
# ============================================================
# Prueba aislada de almacenamiento documental de NIA.
#
# Este test valida:
# - cargar variables locales desde .env
# - leer documentos con file_reader.py
# - guardar documentos en MongoDB technical_documents
# - listar documentos guardados
# - recuperar chunks guardados
# - ejecutar retrieval sobre chunks desde MongoDB
#
# NO toca:
# - nia_orchestrator.py
# - products_catalog
# - flujo conversacional de producción
#
# IMPORTANTE:
# Este test necesita que exista en tu .env:
# MONGO_CONNECTION_STRING=mongodb+srv://...
# ============================================================

from __future__ import annotations

import os
from dotenv import load_dotenv

# ============================================================
# CARGA DE VARIABLES DE ENTORNO
# ============================================================
# Debe ejecutarse ANTES de importar services.document_store.
# services.document_store usa services.mongo, y services.mongo
# busca os.getenv("MONGO_CONNECTION_STRING").
# ============================================================

load_dotenv()


# ============================================================
# IMPORTS DEL PROYECTO
# ============================================================

from knowledge.file_reader import read_knowledge_folder

from services.document_store import (
    ensure_document_indexes,
    save_folder_result,
    list_documents,
    get_all_active_chunks,
)

from retrieval.document_retriever import (
    retrieve_document_chunks,
    build_document_context,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

FOLDER_TO_TEST = "knowledge/nia_os"
SOURCE_TYPE = "nia_os"
TAGS = ["nia_os", "don_andres", "reglas"]


# ============================================================
# VALIDACIÓN PREVIA
# ============================================================

def validate_environment() -> bool:
    """
    Valida que MONGO_CONNECTION_STRING exista antes de conectarse.
    """
    mongo_uri = os.getenv("MONGO_CONNECTION_STRING")

    if not mongo_uri:
        print("\nERROR:")
        print("No se encontró la variable MONGO_CONNECTION_STRING.")
        print("Verifica que tu archivo .env exista en la raíz del proyecto y tenga:")
        print("MONGO_CONNECTION_STRING=mongodb+srv://...")
        print("\nNo pegues la URI en el chat por seguridad.")
        return False

    print("Variable MONGO_CONNECTION_STRING detectada correctamente.")
    return True


# ============================================================
# IMPRESIÓN AUXILIAR
# ============================================================

def print_separator(title: str) -> None:
    """
    Imprime separador visual para la terminal.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_errors(errors: list) -> None:
    """
    Imprime errores de forma segura.
    """
    if not errors:
        return

    print("\nERRORES:")
    for error in errors:
        print("-", error)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta prueba documental completa contra MongoDB.
    """
    print_separator("NIA DOCUMENT STORE TEST")

    # --------------------------------------------------------
    # 0. Validar entorno local
    # --------------------------------------------------------
    print("\n0. Validando variables de entorno...")

    if not validate_environment():
        return

    # --------------------------------------------------------
    # 1. Crear/verificar índices
    # --------------------------------------------------------
    print("\n1. Creando/verificando índices...")

    try:
        index_result = ensure_document_indexes()
        print("Índices OK:", index_result.get("ok"))
        print("Colección:", index_result.get("collection"))
        print("Índices:", index_result.get("indexes"))

    except Exception as error:
        print("\nERROR creando índices:")
        print(error)
        return

    # --------------------------------------------------------
    # 2. Leer carpeta de conocimiento
    # --------------------------------------------------------
    print("\n2. Leyendo carpeta de conocimiento...")

    folder_result = read_knowledge_folder(FOLDER_TO_TEST)

    print("Lectura OK:", folder_result.get("ok"))
    print("Resumen lectura:", folder_result.get("summary"))

    if not folder_result.get("ok"):
        print_errors(folder_result.get("errors", []))
        return

    # --------------------------------------------------------
    # 3. Guardar documentos en MongoDB
    # --------------------------------------------------------
    print("\n3. Guardando documentos en MongoDB...")

    save_result = save_folder_result(
        folder_result=folder_result,
        source_type=SOURCE_TYPE,
        tags=TAGS,
    )

    print("Guardado OK:", save_result.get("ok"))
    print("Resumen guardado:", save_result.get("summary"))

    print_errors(save_result.get("errors", []))

    if not save_result.get("ok"):
        print("\nEl guardado tuvo errores. Revisa el detalle anterior.")
        return

    # --------------------------------------------------------
    # 4. Listar documentos guardados
    # --------------------------------------------------------
    print("\n4. Listando documentos guardados...")

    docs = list_documents(
        source_type=SOURCE_TYPE,
        limit=20,
    )

    print("Documentos encontrados:", len(docs))

    for doc in docs:
        metadata = doc.get("metadata", {}) or {}

        print(
            f"- {doc.get('file_name')} | "
            f"source_type={doc.get('source_type')} | "
            f"chunks={metadata.get('chunk_count')} | "
            f"status={doc.get('status')}"
        )

    # --------------------------------------------------------
    # 5. Recuperar chunks activos desde MongoDB
    # --------------------------------------------------------
    print("\n5. Recuperando chunks activos desde MongoDB...")

    chunks = get_all_active_chunks(
        source_type=SOURCE_TYPE,
        limit_documents=50,
    )

    print("Chunks recuperados:", len(chunks))

    if not chunks:
        print("No se recuperaron chunks. No se puede probar retrieval.")
        return

    # --------------------------------------------------------
    # 6. Probar retrieval sobre chunks guardados
    # --------------------------------------------------------
    print("\n6. Probando retrieval sobre chunks guardados...")

    query = "reglas para no inventar productos"

    retrieval_result = retrieve_document_chunks(
        query=query,
        chunks=chunks,
        top_k=3,
        min_score=0.01,
    )

    print("Query:", query)
    print("Retrieval OK:", retrieval_result.get("ok"))
    print("Metadata:", retrieval_result.get("metadata"))

    print_errors(retrieval_result.get("errors", []))

    print("\nResultados retrieval:")

    for index, item in enumerate(retrieval_result.get("results", []), start=1):
        preview = (item.get("text") or "")[:300].replace("\n", " ")

        print(
            f"{index}. {item.get('source')} | "
            f"score={item.get('score')} | "
            f"preview={preview}"
        )

    # --------------------------------------------------------
    # 7. Construir contexto documental compacto
    # --------------------------------------------------------
    print("\n7. Construyendo contexto documental compacto...")

    context = build_document_context(
        retrieval_result=retrieval_result,
        max_chars=1200,
    )

    print("Fuentes:", context.get("sources"))
    print("Chunks contexto:", context.get("chunk_count"))
    print("Preview contexto:")
    print((context.get("context_text") or "")[:1200])

    print("\nFIN TEST DOCUMENT STORE")
    print("=" * 70)


if __name__ == "__main__":
    main()