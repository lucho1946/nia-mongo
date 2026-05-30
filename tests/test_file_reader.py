# ============================================================
# test_file_reader.py
# ============================================================
# Prueba aislada del lector de archivos de NIA.
#
# Este test NO toca:
# - orquestador
# - memoria
# - catÃ¡logo
# - MongoDB
# - Azure
#
# Solo valida que knowledge/file_reader.py pueda:
# - leer archivos
# - limpiar texto
# - dividir en chunks
# - devolver estructura estÃ¡ndar
# ============================================================

from pathlib import Path

from knowledge.file_reader import (
    read_knowledge_file,
    read_knowledge_folder,
)


# ============================================================
# CONFIGURACIÃ“N DE PRUEBA
# ============================================================

# Cambia esta ruta para probar un archivo especÃ­fico.
# Ejemplos:
# FILE_TO_TEST = "knowledge/nia_os/module_index.json"
# FILE_TO_TEST = "knowledge/nia_os/modules/module_vision_archivos.json"
FILE_TO_TEST = "knowledge/nia_os/module_index.json"

# Cambia esta ruta para probar una carpeta completa.
FOLDER_TO_TEST = "knowledge/nia_os"


# ============================================================
# UTILIDADES DE IMPRESIÃ“N
# ============================================================

def print_file_result(result: dict) -> None:
    """
    Imprime resumen legible de un archivo leÃ­do.
    """
    print("\n" + "=" * 60)
    print("NIA FILE READER TEST")
    print("=" * 60)

    print("OK:", result.get("ok"))
    print("Archivo:", result.get("file_name"))
    print("Tipo:", result.get("file_type"))

    metadata = result.get("metadata", {}) or {}

    print("Caracteres:", metadata.get("chars"))
    print("Chunks:", metadata.get("chunk_count"))

    if result.get("errors"):
        print("\nERRORES:")
        for error in result.get("errors", []):
            print("-", error)

    chunks = result.get("chunks", [])

    if chunks:
        print("\nPRIMER CHUNK:")
        print("-" * 60)
        print(chunks[0].get("text", "")[:1000])
        print("-" * 60)

    print("\nFIN TEST ARCHIVO")
    print("=" * 60)


def print_folder_result(result: dict) -> None:
    """
    Imprime resumen legible de una carpeta leÃ­da.
    """
    print("\n" + "=" * 60)
    print("NIA FOLDER READER TEST")
    print("=" * 60)

    print("OK:", result.get("ok"))
    print("Carpeta:", result.get("folder_path"))

    summary = result.get("summary", {}) or {}

    print("Total archivos:", summary.get("total_files"))
    print("Archivos OK:", summary.get("ok_files"))
    print("Archivos con error:", summary.get("error_files"))
    print("Total chunks:", summary.get("total_chunks"))

    files = result.get("files", [])

    print("\nARCHIVOS LEÃDOS:")
    for item in files:
        metadata = item.get("metadata", {}) or {}
        print(
            f"- {item.get('file_name')} | "
            f"ok={item.get('ok')} | "
            f"tipo={item.get('file_type')} | "
            f"chunks={metadata.get('chunk_count')}"
        )

    if result.get("errors"):
        print("\nERRORES:")
        for error in result.get("errors", []):
            print("-", error)

    print("\nFIN TEST CARPETA")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta pruebas bÃ¡sicas.
    """
    file_path = Path(FILE_TO_TEST)
    folder_path = Path(FOLDER_TO_TEST)

    print("\nProbando archivo individual...")
    file_result = read_knowledge_file(file_path)
    print_file_result(file_result)

    print("\nProbando carpeta completa...")
    folder_result = read_knowledge_folder(folder_path)
    print_folder_result(folder_result)


if __name__ == "__main__":
    main()

