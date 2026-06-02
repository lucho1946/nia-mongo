# ============================================================
# tests/test_openai_service_config.py
# ============================================================
# OBJETIVO:
# Validar que services/ai.py ahora sea una capa segura de OpenAI,
# no el cerebro antiguo de NIA.
#
# No se llama a la API real.
# No consume tokens.
# Solo valida configuración y modo deshabilitado.
# ============================================================

import json
import os

from services.ai import (
    get_openai_config,
    is_openai_enabled,
    openai_health,
    generate_assisted_response,
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
        "OPENAI_TIMEOUT_SECONDS": os.environ.get("OPENAI_TIMEOUT_SECONDS"),
    }


def restore_env(snapshot):
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def run_case_default_disabled_even_with_key():
    print_section("CASO 1: OpenAI deshabilitado por defecto aunque exista API key")

    snapshot = backup_env()

    try:
        os.environ["OPENAI_API_KEY"] = "test_fake_key"
        os.environ.pop("OPENAI_ENABLED", None)
        os.environ.pop("OPENAI_MODEL", None)

        config = get_openai_config()

        show_json("OPENAI CONFIG DEFAULT", config)

        assert_condition(
            config.get("api_key_configured") is True,
            "Debe detectar API key configurada.",
        )

        assert_condition(
            config.get("enabled") is False,
            "Debe estar deshabilitado por defecto.",
        )

        assert_condition(
            config.get("ready") is False,
            "No debe estar ready si OPENAI_ENABLED no está en true.",
        )

        assert_condition(
            config.get("model") == "gpt-4o-mini",
            "Debe usar modelo por defecto.",
        )

        assert_condition(
            is_openai_enabled() is False,
            "is_openai_enabled debe retornar False.",
        )

    finally:
        restore_env(snapshot)


def run_case_enabled_with_config():
    print_section("CASO 2: OpenAI ready con enabled true y API key")

    snapshot = backup_env()

    try:
        os.environ["OPENAI_API_KEY"] = "test_fake_key"
        os.environ["OPENAI_ENABLED"] = "true"
        os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

        config = get_openai_config()

        show_json("OPENAI CONFIG ENABLED", config)

        assert_condition(
            config.get("enabled") is True,
            "Debe quedar enabled true.",
        )

        assert_condition(
            config.get("ready") is True,
            "Debe quedar ready true.",
        )

        assert_condition(
            config.get("model") == "gpt-4o-mini",
            "Debe usar modelo configurado.",
        )

        assert_condition(
            is_openai_enabled() is True,
            "is_openai_enabled debe retornar True.",
        )

    finally:
        restore_env(snapshot)


def run_case_health_does_not_expose_key():
    print_section("CASO 3: health no expone API key")

    snapshot = backup_env()

    try:
        os.environ["OPENAI_API_KEY"] = "test_fake_secret_key"
        os.environ["OPENAI_ENABLED"] = "true"

        health = openai_health()

        show_json("OPENAI HEALTH", health)

        serialized = json.dumps(health, ensure_ascii=False)

        assert_condition(
            "test_fake_secret_key" not in serialized,
            "Health no debe exponer la API key.",
        )

        assert_condition(
            health.get("api_key_configured") is True,
            "Debe indicar que hay API key sin mostrarla.",
        )

    finally:
        restore_env(snapshot)


def run_case_generate_returns_fallback_when_disabled():
    print_section("CASO 4: generate_assisted_response usa fallback si está deshabilitado")

    snapshot = backup_env()

    try:
        os.environ["OPENAI_API_KEY"] = "test_fake_key"
        os.environ["OPENAI_ENABLED"] = "false"
        os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

        result = generate_assisted_response(
            user_message="Necesito medir velocidad de aire.",
            safe_context="",
            fallback_response="Respuesta segura sin OpenAI.",
        )

        show_json("OPENAI DISABLED FALLBACK", result)

        assert_condition(
            result.get("ok") is False,
            "No debe marcar ok si no usó OpenAI.",
        )

        assert_condition(
            result.get("used_openai") is False,
            "No debe usar OpenAI si está deshabilitado.",
        )

        assert_condition(
            result.get("response") == "Respuesta segura sin OpenAI.",
            "Debe devolver fallback.",
        )

    finally:
        restore_env(snapshot)


def main():
    print("=" * 70)
    print("NIA OPENAI SERVICE CONFIG TEST")
    print("=" * 70)

    run_case_default_disabled_even_with_key()
    run_case_enabled_with_config()
    run_case_health_does_not_expose_key()
    run_case_generate_returns_fallback_when_disabled()

    print("\nFIN TEST OPENAI SERVICE CONFIG ✅")


if __name__ == "__main__":
    main()