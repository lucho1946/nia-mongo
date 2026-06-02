# ============================================================
# tests/test_openai_intent_interpreter.py
# ============================================================
# OBJETIVO:
# Validar que el intérprete OpenAI de intención funciona de forma
# segura y no rompe si OpenAI está apagado.
#
# No llama a OpenAI real.
# No consume tokens.
# ============================================================

import json
import os

from orchestration.openai_intent_interpreter import (
    fallback_interpret_open_need,
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


def backup_env():
    return {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_ENABLED": os.environ.get("OPENAI_ENABLED"),
        "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
    }


def restore_env(snapshot):
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def run_case_fallback_air_speed_need():
    print_section("CASO 1: fallback interpreta necesidad de velocidad de aire")

    result = fallback_interpret_open_need(
        "Hola, estoy buscando un equipo para medir la velocidad del aire en ductos de ventilación."
    )

    show_json("FALLBACK AIR SPEED NEED", result)

    assert_condition(
        result.get("used_openai") is False,
        "Fallback no debe usar OpenAI.",
    )

    assert_condition(
        result.get("intent_candidate") == "producto",
        "Debe interpretar intención de producto.",
    )

    assert_condition(
        result.get("needs_catalog_search") is True,
        "Debe indicar búsqueda en catálogo.",
    )

    assert_condition(
        "anemómetro" in result.get("normalized_query", "").lower()
        or "anemometro" in result.get("normalized_query", "").lower(),
        "La query debe apuntar a anemómetro.",
    )


def run_case_interpreter_disabled_uses_fallback():
    print_section("CASO 2: intérprete usa fallback si OpenAI está deshabilitado")

    snapshot = backup_env()

    try:
        os.environ["OPENAI_API_KEY"] = "test_fake_key"
        os.environ["OPENAI_ENABLED"] = "false"
        os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

        result = interpret_open_customer_need(
            "Necesito medir velocidad de aire en ductos."
        )

        show_json("INTERPRETER DISABLED RESULT", result)

        assert_condition(
            result.get("used_openai") is False,
            "No debe usar OpenAI si está deshabilitado.",
        )

        assert_condition(
            result.get("intent_candidate") == "producto",
            "Debe interpretar producto con fallback.",
        )

        assert_condition(
            result.get("needs_catalog_search") is True,
            "Debe sugerir búsqueda en catálogo.",
        )

    finally:
        restore_env(snapshot)


def run_case_general_message_asks_one_question():
    print_section("CASO 3: mensaje general sugiere una sola pregunta")

    snapshot = backup_env()

    try:
        os.environ["OPENAI_API_KEY"] = "test_fake_key"
        os.environ["OPENAI_ENABLED"] = "false"
        os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

        result = interpret_open_customer_need("Hola, necesito ayuda.")

        show_json("GENERAL MESSAGE RESULT", result)

        assert_condition(
            result.get("used_openai") is False,
            "No debe usar OpenAI.",
        )

        assert_condition(
            result.get("should_ask") is True,
            "Debe sugerir preguntar si no hay intención clara.",
        )

        question = result.get("suggested_question", "")

        assert_condition(
            question.count("?") + question.count("¿") <= 2,
            "Debe sugerir máximo una pregunta.",
        )

    finally:
        restore_env(snapshot)


def main():
    print("=" * 70)
    print("NIA OPENAI INTENT INTERPRETER TEST")
    print("=" * 70)

    run_case_fallback_air_speed_need()
    run_case_interpreter_disabled_uses_fallback()
    run_case_general_message_asks_one_question()

    print("\nFIN TEST OPENAI INTENT INTERPRETER ✅")


if __name__ == "__main__":
    main()