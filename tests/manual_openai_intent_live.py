# ============================================================
# tests/manual_openai_intent_live.py
# ============================================================
# OBJETIVO:
# Probar OpenAI real con el intérprete semántico de NIA.
#
# IMPORTANTE:
# - Este test SÍ consume API key/tokens.
# - No debe ejecutarse en regresión automática.
# - Solo valida interpretación estructurada.
# - No busca productos directamente.
# - No recomienda por cuenta de OpenAI.
#
# Arquitectura validada:
# - OpenAI interpreta intención y necesidad.
# - Los libros industriales apoyan la interpretación técnica.
# - OpenAI NO recomienda producto final.
# - OpenAI NO inventa precio, stock ni disponibilidad.
# - OpenAI NO devuelve family_hint.
# - OpenAI NO devuelve catalog_line_hints.
# - Catálogo real decide productos después.
# ============================================================

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# BOOTSTRAP DE IMPORTS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


load_dotenv()

# Forzamos prueba real.
os.environ["OPENAI_ENABLED"] = "true"
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")


from services.ai import openai_health  # noqa: E402
from orchestration.openai_intent_interpreter import (  # noqa: E402
    interpret_open_customer_need,
)


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
        result.get("source") == "openai",
        "La fuente debe ser openai.",
    )

    assert_condition(
        result.get("intent_candidate") in ["producto", "cotizacion", "general"],
        "Debe devolver una intención válida.",
    )

    assert_condition(
        isinstance(result.get("confidence"), float),
        "Debe devolver confidence como número.",
    )

    assert_condition(
        "normalized_query" in result,
        "Debe devolver normalized_query.",
    )

    assert_condition(
        result.get("normalized_query"),
        "Debe generar normalized_query.",
    )

    assert_condition(
        "need_type" in result,
        "Debe devolver need_type.",
    )

    assert_condition(
        "required_action" in result,
        "Debe devolver required_action.",
    )

    assert_condition(
        "required_target" in result,
        "Debe devolver required_target.",
    )

    assert_condition(
        "application_context" in result,
        "Debe devolver application_context.",
    )

    assert_condition(
        isinstance(result.get("product_need_terms"), list),
        "product_need_terms debe ser lista.",
    )

    assert_condition(
        isinstance(result.get("technical_signals"), list),
        "technical_signals debe ser lista.",
    )

    assert_condition(
        isinstance(result.get("commercial_signals"), list),
        "commercial_signals debe ser lista.",
    )

    assert_condition(
        "decision_reason" in result,
        "Debe devolver decision_reason.",
    )

    assert_condition(
        "industrial_context" in result,
        "Debe incluir metadata de industrial_context.",
    )

    industrial_context = result.get("industrial_context", {})

    assert_condition(
        isinstance(industrial_context, dict),
        "industrial_context debe ser dict.",
    )

    assert_condition(
        "used" in industrial_context,
        "industrial_context debe indicar si se usó contexto.",
    )

    assert_condition(
        "result_count" in industrial_context,
        "industrial_context debe incluir result_count.",
    )

    assert_condition(
        "reason" in industrial_context,
        "industrial_context debe incluir reason.",
    )

    assert_condition(
        result.get("family_hint") == "",
        "family_hint debe venir vacío; ya no usamos familias manuales.",
    )

    assert_condition(
        result.get("catalog_line_hints") == {},
        "catalog_line_hints debe venir vacío; OpenAI no debe inventar líneas.",
    )

    forbidden_values = json.dumps(result, ensure_ascii=False).lower()

    assert_condition(
        "recommended_product" not in forbidden_values,
        "OpenAI no debe recomendar producto final.",
    )

    assert_condition(
        '"price"' not in forbidden_values and '"stock"' not in forbidden_values,
        "OpenAI no debe devolver precio ni stock.",
    )

    print("\nFIN TEST OPENAI INTENT LIVE ✅")


if __name__ == "__main__":
    main()