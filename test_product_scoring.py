# ============================================================
# test_product_scoring.py
# ============================================================
# Prueba segura del scoring de productos para NIA.
#
# Este test:
# - carga .env
# - lee el Excel de Don Andrés
# - valida columnas CODIGO y score
# - ejecuta dry-run contra MongoDB
# - NO modifica products_catalog
#
# IMPORTANTE:
# Este test NO actualiza MongoDB.
# Para actualizar se usa etl_apply_product_scoring.py --apply
# ============================================================

from __future__ import annotations

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from services.product_scoring import (
    read_scoring_excel,
    apply_product_scores,
    preview_scoring_records,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

EXCEL_PATH = "productos-289496 con Score para Nia.xlsx"
MAX_ROWS_TEST = 1000


# ============================================================
# UTILIDADES
# ============================================================

def print_json(title: str, payload: dict) -> None:
    """
    Imprime JSON legible.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def validate_environment() -> bool:
    """
    Valida .env para poder consultar MongoDB.
    """
    if not os.getenv("MONGO_CONNECTION_STRING"):
        print("\nERROR:")
        print("No se encontró MONGO_CONNECTION_STRING en el entorno.")
        print("Verifica tu archivo .env en la raíz del proyecto.")
        return False

    print("Variable MONGO_CONNECTION_STRING detectada correctamente.")
    return True


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta prueba de scoring en modo seguro.
    """
    print("\n" + "=" * 70)
    print("NIA PRODUCT SCORING TEST")
    print("=" * 70)

    print("\n0. Validando entorno...")

    if not validate_environment():
        return

    excel_path = Path(EXCEL_PATH)

    print("\n1. Validando archivo Excel...")
    print("Excel:", excel_path)

    if not excel_path.exists():
        print("\nERROR:")
        print(f"No existe el archivo: {excel_path}")
        print("Copia el Excel de Don Andrés en la raíz del proyecto o ajusta EXCEL_PATH.")
        return

    print("\n2. Leyendo muestra del Excel...")
    read_result = read_scoring_excel(
        excel_path=excel_path,
        max_rows=MAX_ROWS_TEST,
    )

    print_json("RESUMEN LECTURA EXCEL", {
        "ok": read_result.get("ok"),
        "summary": read_result.get("summary"),
        "errors": read_result.get("errors"),
        "sample": preview_scoring_records(
            read_result.get("records", []),
            limit=10,
        ),
    })

    if not read_result.get("ok"):
        print("\nNo se puede continuar porque la lectura del Excel falló.")
        return

    records = read_result.get("records", [])

    if not records:
        print("\nNo hay registros válidos para probar.")
        return

    print("\n3. Ejecutando dry-run contra MongoDB...")
    dry_run_result = apply_product_scores(
        records=records,
        dry_run=True,
        score_source="excel_don_andres_test",
        score_version="test",
        batch_size=500,
    )

    print_json("RESULTADO DRY-RUN", dry_run_result)

    print("\nFIN TEST PRODUCT SCORING")
    print("=" * 70)


if __name__ == "__main__":
    main()