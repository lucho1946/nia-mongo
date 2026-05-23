# ============================================================
# etl_apply_product_scoring.py
# ============================================================
# Script ETL para aplicar el score de Don Andrés al catálogo
# real de productos en MongoDB.
#
# Uso seguro:
# 1. Primero correr en dry-run:
#    python etl_apply_product_scoring.py --excel "productos-289496 con Score para Nia.xlsx" --max-rows 1000
#
# 2. Luego correr completo en dry-run:
#    python etl_apply_product_scoring.py --excel "productos-289496 con Score para Nia.xlsx"
#
# 3. Solo cuando esté validado, aplicar:
#    python etl_apply_product_scoring.py --excel "productos-289496 con Score para Nia.xlsx" --apply
#
# IMPORTANTE:
# - Por defecto NO modifica MongoDB.
# - Solo actualiza cuando se pasa --apply.
# ============================================================

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# Cargar .env antes de usar servicios MongoDB.
load_dotenv()

from services.product_scoring import apply_scoring_from_excel


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEFAULT_EXCEL_PATH = "productos-289496 con Score para Nia.xlsx"
DEFAULT_SCORE_SOURCE = "excel_don_andres"


# ============================================================
# UTILIDADES
# ============================================================

def print_json(title: str, payload: Dict[str, Any]) -> None:
    """
    Imprime JSON legible en consola.
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
    Valida que exista MONGO_CONNECTION_STRING.
    """
    if not os.getenv("MONGO_CONNECTION_STRING"):
        print("\nERROR:")
        print("No se encontró MONGO_CONNECTION_STRING.")
        print("Verifica que exista .env en la raíz del proyecto.")
        print("No pegues la URI en el chat por seguridad.")
        return False

    return True


def build_parser() -> argparse.ArgumentParser:
    """
    Construye argumentos de línea de comandos.
    """
    parser = argparse.ArgumentParser(
        description="Aplica score_nia desde Excel al catálogo MongoDB products_catalog."
    )

    parser.add_argument(
        "--excel",
        default=DEFAULT_EXCEL_PATH,
        help="Ruta del Excel con columnas CODIGO y score.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Si se incluye, actualiza MongoDB. Si no, corre en dry-run.",
    )

    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Cantidad máxima de filas a leer del Excel. Útil para pruebas.",
    )

    parser.add_argument(
        "--version",
        default=None,
        help="Versión del scoring. Ej: 2026-05-23. Si no se envía, usa fecha actual.",
    )

    parser.add_argument(
        "--source",
        default=DEFAULT_SCORE_SOURCE,
        help="Fuente del scoring.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Tamaño de lote para consultas/actualizaciones MongoDB.",
    )

    return parser


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta ETL de scoring.
    """
    parser = build_parser()
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("NIA PRODUCT SCORING ETL")
    print("=" * 70)

    if not validate_environment():
        return

    excel_path = Path(args.excel)

    print(f"Excel: {excel_path}")
    print(f"Modo: {'APLICAR EN MONGODB' if args.apply else 'DRY-RUN / SIN MODIFICAR'}")
    print(f"Max rows: {args.max_rows}")
    print(f"Score source: {args.source}")
    print(f"Score version: {args.version or 'fecha actual'}")
    print(f"Batch size: {args.batch_size}")

    if not excel_path.exists():
        print("\nERROR:")
        print(f"No existe el archivo Excel: {excel_path}")
        return

    result = apply_scoring_from_excel(
        excel_path=excel_path,
        dry_run=not args.apply,
        max_rows=args.max_rows,
        score_version=args.version,
        score_source=args.source,
        batch_size=args.batch_size,
    )

    print_json("RESULTADO ETL SCORING", result)

    if result.get("ok"):
        print("\nProceso finalizado correctamente.")
    else:
        print("\nEl proceso finalizó con errores. Revisa el JSON anterior.")

    if not args.apply:
        print("\nNOTA:")
        print("Este fue un dry-run. No se modificó MongoDB.")
        print("Para aplicar realmente, ejecuta nuevamente agregando: --apply")


if __name__ == "__main__":
    main()