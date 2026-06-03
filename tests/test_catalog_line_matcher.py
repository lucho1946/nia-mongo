# ============================================================
# tests/test_catalog_line_matcher.py
# ============================================================
# OBJETIVO:
# Validar que el nuevo matcher de catálogo ya no depende de familias
# manuales y prioriza:
# - NIVEL_0 a NIVEL_4
# - DESCRIPCION_CORTA_PRE
# - DESCRIPCION_LARGA_PRE con menor peso
# ============================================================

from pathlib import Path
import sys


# ============================================================
# BOOTSTRAP DE IMPORTS
# ============================================================
# Permite ejecutar este test de dos formas:
#
# 1. Directo:
#    python tests/test_catalog_line_matcher.py
#
# 2. Con pytest:
#    python -m pytest tests/test_catalog_line_matcher.py -v
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from services.catalog_line_matcher import evaluate_catalog_line_match  # noqa: E402


def assert_condition(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def run_case_catalog_line_beats_long_description_noise():
    """
    Un producto cuya línea real coincide debe ganarle a un producto
    que solo menciona la palabra en descripción larga.
    """
    query = "anemometro velocidad aire ductos"

    product_line_match = {
        "CODIGO": "P1",
        "REFERENCIA": "ANEMO-1",
        "MARCA_LET": "lutron",
        "NIVEL_0": "Instrumentos de medición",
        "NIVEL_1": "anemometros",
        "NIVEL_2": "anemometros digitales portatiles",
        "NIVEL_3": "anemometros para velocidad de aire",
        "NIVEL_4": "anemometros para ductos",
        "DESCRIPCION_CORTA_PRE": "Anemometro digital portatil",
        "DESCRIPCION_LARGA_PRE": "Equipo para medicion de velocidad del aire.",
        "texto_busqueda": "anemometro velocidad aire ductos",
    }

    product_long_description_only = {
        "CODIGO": "P2",
        "REFERENCIA": "GEN-1",
        "MARCA_LET": "generica",
        "NIVEL_0": "Equipos industriales",
        "NIVEL_1": "maquinaria",
        "NIVEL_2": "equipos de proceso",
        "NIVEL_3": "equipos generales",
        "NIVEL_4": "equipos generales",
        "DESCRIPCION_CORTA_PRE": "Equipo industrial general",
        "DESCRIPCION_LARGA_PRE": "Incluye ventilador interno y menciona velocidad de aire en el manual.",
        "texto_busqueda": "equipo industrial general ventilador interno velocidad aire",
    }

    score_line = evaluate_catalog_line_match(query, product_line_match)
    score_long = evaluate_catalog_line_match(query, product_long_description_only)

    assert_condition(
        score_line["score"] > score_long["score"],
        f"El match por línea debe ganar. line={score_line} long={score_long}",
    )

    assert_condition(
        "NIVEL_4" in score_line["matched_levels"]
        or "NIVEL_3" in score_line["matched_levels"]
        or "NIVEL_2" in score_line["matched_levels"],
        f"Debe detectar match en niveles del catálogo. Debug: {score_line}",
    )


def run_case_short_description_beats_long_description():
    """
    La descripción corta debe pesar más que la descripción larga.
    """
    query = "sensor inductivo 24v pnp"

    product_short = {
        "CODIGO": "S1",
        "REFERENCIA": "S-IN-PNP",
        "MARCA_LET": "ifm",
        "NIVEL_0": "automatizacion",
        "NIVEL_1": "sensores",
        "NIVEL_2": "sensores inductivos",
        "NIVEL_3": "sensores inductivos pnp",
        "NIVEL_4": "sensores inductivos 24v pnp",
        "DESCRIPCION_CORTA_PRE": "Sensor inductivo 24V PNP",
        "DESCRIPCION_LARGA_PRE": "",
        "texto_busqueda": "sensor inductivo 24v pnp",
    }

    product_long = {
        "CODIGO": "S2",
        "REFERENCIA": "CTRL-1",
        "MARCA_LET": "otra",
        "NIVEL_0": "automatizacion",
        "NIVEL_1": "controladores",
        "NIVEL_2": "modulos",
        "NIVEL_3": "modulos de control",
        "NIVEL_4": "modulos de control",
        "DESCRIPCION_CORTA_PRE": "Modulo controlador",
        "DESCRIPCION_LARGA_PRE": "Compatible con sensor inductivo 24V PNP en aplicaciones externas.",
        "texto_busqueda": "modulo controlador sensor inductivo 24v pnp",
    }

    score_short = evaluate_catalog_line_match(query, product_short)
    score_long = evaluate_catalog_line_match(query, product_long)

    assert_condition(
        score_short["score"] > score_long["score"],
        f"Descripción corta/línea debe ganar sobre descripción larga. short={score_short} long={score_long}",
    )


def run_case_accessory_penalty_when_not_requested():
    """
    Si el usuario no pide accesorio/repuesto, un accesorio debe bajar.
    """
    query = "variador 3hp 220v"

    main_product = {
        "CODIGO": "V1",
        "REFERENCIA": "VFD-3HP",
        "MARCA_LET": "weg",
        "NIVEL_0": "automatizacion",
        "NIVEL_1": "variadores",
        "NIVEL_2": "variadores de frecuencia",
        "NIVEL_3": "variadores 220v",
        "NIVEL_4": "variadores 3hp 220v",
        "DESCRIPCION_CORTA_PRE": "Variador de frecuencia 3HP 220V",
        "DESCRIPCION_LARGA_PRE": "",
        "texto_busqueda": "variador frecuencia 3hp 220v",
    }

    accessory = {
        "CODIGO": "V2",
        "REFERENCIA": "PANEL-VFD",
        "MARCA_LET": "weg",
        "NIVEL_0": "automatizacion",
        "NIVEL_1": "variadores",
        "NIVEL_2": "accesorios para variadores",
        "NIVEL_3": "paneles",
        "NIVEL_4": "panel teclado variador",
        "DESCRIPCION_CORTA_PRE": "Panel teclado para variador",
        "DESCRIPCION_LARGA_PRE": "Accesorio para variador de frecuencia.",
        "texto_busqueda": "panel teclado accesorio variador",
    }

    score_main = evaluate_catalog_line_match(query, main_product)
    score_accessory = evaluate_catalog_line_match(query, accessory)

    assert_condition(
        score_main["score"] > score_accessory["score"],
        f"Producto principal debe ganar sobre accesorio. main={score_main} accessory={score_accessory}",
    )

    assert_condition(
        score_accessory["secondary_penalty"] < 0,
        f"Accesorio debe tener penalización. Debug: {score_accessory}",
    )

# ============================================================
# TESTS PYTEST
# ============================================================

def test_catalog_line_beats_long_description_noise():
    """
    Pytest: valida que la línea real del catálogo pese más que
    una mención débil en descripción larga.
    """
    run_case_catalog_line_beats_long_description_noise()


def test_short_description_beats_long_description():
    """
    Pytest: valida que DESCRIPCION_CORTA_PRE pese más que
    DESCRIPCION_LARGA_PRE.
    """
    run_case_short_description_beats_long_description()


def test_accessory_penalty_when_not_requested():
    """
    Pytest: valida que un accesorio/repuesto baje cuando
    el usuario no lo pidió explícitamente.
    """
    run_case_accessory_penalty_when_not_requested()

def main():
    print("=" * 70)
    print("CATALOG LINE MATCHER TEST")
    print("=" * 70)

    run_case_catalog_line_beats_long_description_noise()
    run_case_short_description_beats_long_description()
    run_case_accessory_penalty_when_not_requested()

    print("\nFIN TEST CATALOG LINE MATCHER ✅")


if __name__ == "__main__":
    main()