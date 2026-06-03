# ============================================================
# tests/test_regression_manual_scripts.py
# ============================================================
# OBJETIVO:
# Permitir que pytest ejecute los tests manuales existentes
# sin tener que modificar uno por uno todos los archivos.
#
# Por qué existe:
# - Los tests actuales fueron escritos como scripts ejecutables:
#   python tests/test_x.py
#
# - Pytest solo recolecta automáticamente funciones que empiezan
#   por test_.
#
# - Este archivo actúa como puente:
#   pytest -> ejecuta cada script manual -> si hay AssertionError,
#   Traceback o error de conexión, pytest lo marca como fallido.
#
# Importante:
# - NO consume tokens OpenAI si los scripts mantienen OPENAI_ENABLED=false.
# - NO reemplaza los tests actuales.
# - NO toca lógica de producción.
# ============================================================

from __future__ import annotations

import runpy
from pathlib import Path

import pytest


# Carpeta raíz de tests/
TESTS_DIR = Path(__file__).resolve().parent


# ============================================================
# SUITE DE REGRESIÓN SEGURA
# ============================================================
# Estos son los scripts que queremos validar antes de pasar
# cambios de desarrollo a main.
#
# No incluimos tests live/manuales que consuman tokens reales,
# como manual_openai_intent_live.py.
# ============================================================

REGRESSION_SCRIPTS = [
    "test_catalog_line_matcher.py",
    "test_openai_service_config.py",
    "test_openai_intent_interpreter.py",
    "test_semantic_need_profiles.py",
    "test_chat_endpoint_open_need_interpreter.py",
    "test_chat_endpoint_commercial_handoff.py",
    "test_chat_endpoint_public_contract.py",
]


@pytest.mark.parametrize("script_name", REGRESSION_SCRIPTS)
def test_manual_regression_script(script_name: str):
    """
    Ejecuta un script manual existente como si se corriera con:

        python tests/<script_name>

    Si el script lanza AssertionError, ModuleNotFoundError,
    conexión fallida o cualquier excepción no controlada,
    pytest marcará este caso como FAILED.
    """
    script_path = TESTS_DIR / script_name

    assert script_path.exists(), f"No existe el script de prueba: {script_path}"

    runpy.run_path(
        str(script_path),
        run_name="__main__",
    )