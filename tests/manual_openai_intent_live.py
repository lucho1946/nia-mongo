# ============================================================
# tests/manual_openai_intent_live.py
# ============================================================
# OBJETIVO:
# Probar OpenAI real con el intérprete de intención de NIA.
#
# IMPORTANTE:
# - Este test SÍ consume API key/tokens.
# - No debe ejecutarse en regresión automática.
# - Solo valida interpretación estructurada.
# - No busca productos directamente.
# - No recomienda por cuenta de OpenAI.
# ============================================================

import json
import os

from dotenv import load_dotenv

load_dotenv()

# Forzamos prueba real.
os.environ["OPENAI_ENABLED"] = "true"
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")

from services.ai import openai_health  # noqa: E402
from orchestration.openai_intent_interpreter import interpret_open_customer_need  # noqa: E402


def print_section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def show_json(label: str, data):
    print_section(label)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def assert_condition(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def main():
    print("=" * 70)
    print("NIA OPENAI INTENT LIVE TEST")
    print("=" * 70)

    health = openai_health()
    show_json("OPENAI HEALTH", health)

    assert_condition(
        health.get("api_key_configured") is True,
        "OPENAI_API_KEY debe estar configurado.",
    )

    assert_condition(
        health.get("enabled") is True,
        "OPENAI_ENABLED debe estar true para esta prueba.",
    )

    assert_condition(
        health.get("ready") is True,
        "OpenAI debe estar ready.",
    )

    message = (
        "Hola, estoy buscando un equipo para medir la velocidad del aire "
        "en unos ductos de ventilación."
    )

    result = interpret_open_customer_need(message)

    show_json("OPENAI LIVE INTENT RESULT", result)

    assert_condition(
        result.get("used_openai") is True,
        "Debe usar OpenAI real.",
    )

    assert_condition(
        result.get("intent_candidate") in ["producto", "cotizacion"],
        "Debe interpretar intención comercial/producto.",
    )

    assert_condition(
        result.get("needs_catalog_search") is True,
        "Debe indicar búsqueda en catálogo.",
    )

    assert_condition(
        result.get("normalized_query"),
        "Debe generar normalized_query.",
    )

    assert_condition(
        result.get("semantic_profile") in ["velocidad_aire", "", None],
        "Si devuelve perfil, debe ser velocidad_aire para este caso.",
    )

    print("\nFIN TEST OPENAI INTENT LIVE ✅")


if __name__ == "__main__":
    main()