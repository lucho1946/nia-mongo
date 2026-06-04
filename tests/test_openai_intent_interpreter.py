# ============================================================
# tests/test_openai_intent_interpreter.py
# ============================================================
# OBJETIVO:
# Validar que el intérprete OpenAI de intención funciona de forma
# segura y no rompe si OpenAI está apagado.
#
# No llama a OpenAI real.
# No consume tokens.
#
# Arquitectura validada:
# - OpenAI interpreta necesidades abiertas cuando está disponible.
# - El fallback conservador NO intenta reemplazar a OpenAI.
# - El fallback conservador NO usa familias manuales.
# - El fallback conservador NO usa marcas manuales.
# - El fallback conservador NO inventa líneas del catálogo.
# - El fallback conservador SÍ permite búsqueda directa por código exacto.
# ============================================================

import json
import os
import sys
from pathlib import Path


# ============================================================
# BOOTSTRAP DE IMPORTS
# ============================================================
# Permite ejecutar este test de dos formas:
#
# 1. Directo:
#    python tests/test_openai_intent_interpreter.py
#
# 2. Con pytest:
#    python -m pytest tests/test_openai_intent_interpreter.py -v
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from orchestration.openai_intent_interpreter import (  # noqa: E402
    fallback_interpret_open_need,
    interpret_open_customer_need,
)


# ============================================================
# UTILIDADES DE TEST
# ============================================================

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
    """
    Guarda variables de entorno relacionadas con OpenAI para
    restaurarlas después de cada prueba.
    """
    return {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_ENABLED": os.environ.get("OPENAI_ENABLED"),
        "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
    }


def restore_env(snapshot):
    """
    Restaura variables de entorno después de cada prueba.
    """
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ============================================================
# CASO 1
# ============================================================

def run_case_fallback_air_speed_need():
    """
    Valida que el fallback conservador NO interprete necesidades
    abiertas cuando OpenAI no participa.

    Antes el fallback intentaba convertir:
    "velocidad de aire en ductos"
    en una intención de producto.

    Ahora eso NO debe pasar. Esa interpretación semántica le
    corresponde a OpenAI cuando esté disponible.
    """
    print_section("CASO 1: fallback conservador no interpreta necesidad abierta")

    result = fallback_interpret_open_need(
        "Hola, estoy buscando un equipo para medir la velocidad del aire en ductos de ventilación."
    )

    show_json("CONSERVATIVE FALLBACK OPEN NEED", result)

    assert_condition(
        result.get("used_openai") is False,
        "Fallback no debe usar OpenAI.",
    )

    assert_condition(
        result.get("source") == "conservative_fallback",
        "Debe usar fallback conservador.",
    )

    assert_condition(
        result.get("intent_candidate") == "general",
        "Sin OpenAI, una necesidad abierta debe quedar como general.",
    )

    assert_condition(
        result.get("needs_catalog_search") is False,
        "Sin OpenAI, el fallback no debe buscar catálogo por necesidad abierta.",
    )

    assert_condition(
        result.get("should_ask") is True,
        "Debe pedir aclaración si OpenAI no está disponible.",
    )

    assert_condition(
        result.get("family_hint") == "",
        "family_hint debe quedar vacío.",
    )

    assert_condition(
        result.get("catalog_line_hints") == {},
        "catalog_line_hints debe quedar vacío.",
    )

    assert_condition(
        result.get("product_need_terms") == [],
        "El fallback conservador no debe generar términos técnicos manuales.",
    )

    assert_condition(
        result.get("normalized_query") == "",
        "El fallback conservador no debe generar query semántica para necesidad abierta.",
    )


# ============================================================
# CASO 2
# ============================================================

def run_case_interpreter_disabled_uses_fallback():
    """
    Valida que interpret_open_customer_need use fallback conservador
    cuando OpenAI está deshabilitado.

    Importante:
    Aunque el mensaje parezca técnico, si OpenAI está apagado el
    fallback NO debe inventar intención de producto ni normalized_query.
    """
    print_section("CASO 2: intérprete usa fallback conservador si OpenAI está deshabilitado")

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
            result.get("source") == "conservative_fallback",
            "Debe usar fallback conservador.",
        )

        assert_condition(
            result.get("intent_candidate") == "general",
            "Sin OpenAI, una necesidad abierta debe quedar como general.",
        )

        assert_condition(
            result.get("needs_catalog_search") is False,
            "Sin OpenAI, no debe buscar catálogo por una necesidad abierta.",
        )

        assert_condition(
            result.get("should_ask") is True,
            "Debe pedir aclaración cuando OpenAI está deshabilitado.",
        )

        assert_condition(
            result.get("normalized_query") == "",
            "Sin OpenAI, no debe crear query semántica para necesidad abierta.",
        )

        assert_condition(
            result.get("family_hint") == "",
            "family_hint debe quedar vacío.",
        )

        assert_condition(
            result.get("catalog_line_hints") == {},
            "catalog_line_hints debe quedar vacío.",
        )

        assert_condition(
            result.get("product_need_terms") == [],
            "El fallback conservador no debe generar términos técnicos manuales.",
        )

        openai_config = result.get("openai_config", {})

        assert_condition(
            openai_config.get("enabled") is False,
            "La configuración debe reflejar que OpenAI está deshabilitado.",
        )

    finally:
        restore_env(snapshot)


# ============================================================
# CASO 3
# ============================================================

def run_case_general_message_asks_one_question():
    """
    Valida que un mensaje general no dispare búsqueda en catálogo
    y proponga máximo una pregunta de aclaración.
    """
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
            result.get("source") == "conservative_fallback",
            "Debe usar fallback conservador.",
        )

        assert_condition(
            result.get("intent_candidate") == "general",
            "Un mensaje genérico debe quedar como general.",
        )

        assert_condition(
            result.get("needs_catalog_search") is False,
            "Un mensaje genérico no debe buscar en catálogo.",
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


# ============================================================
# CASO 4
# ============================================================

def run_case_fallback_exact_code_searches_catalog():
    """
    Valida que el fallback conservador sí permita búsqueda directa
    cuando el usuario escribe un código exacto.

    Esto no requiere interpretación semántica.
    """
    print_section("CASO 4: fallback conservador permite búsqueda por código exacto")

    result = fallback_interpret_open_need("Tienes el producto P382169 disponible?")

    show_json("CONSERVATIVE FALLBACK EXACT CODE", result)

    assert_condition(
        result.get("used_openai") is False,
        "Fallback no debe usar OpenAI.",
    )

    assert_condition(
        result.get("source") == "conservative_fallback",
        "Debe usar fallback conservador.",
    )

    assert_condition(
        result.get("intent_candidate") == "codigo_producto",
        "Debe detectar intención por código exacto.",
    )

    assert_condition(
        result.get("detected_code") == "P382169",
        "Debe extraer el código exacto.",
    )

    assert_condition(
        result.get("normalized_query") == "P382169",
        "La query debe ser el código exacto.",
    )

    assert_condition(
        result.get("need_type") == "codigo_producto",
        "El tipo de necesidad debe ser codigo_producto.",
    )

    assert_condition(
        result.get("product_need_terms") == ["P382169"],
        "product_need_terms debe contener únicamente el código exacto.",
    )

    assert_condition(
        result.get("needs_catalog_search") is True,
        "Código exacto sí debe buscar en catálogo.",
    )

    assert_condition(
        result.get("should_ask") is False,
        "No debe preguntar cuando hay código exacto.",
    )

    assert_condition(
        result.get("family_hint") == "",
        "family_hint debe quedar vacío.",
    )

    assert_condition(
        result.get("catalog_line_hints") == {},
        "catalog_line_hints debe quedar vacío.",
    )


# ============================================================
# TESTS PYTEST
# ============================================================

def test_fallback_open_need_is_conservative():
    run_case_fallback_air_speed_need()


def test_interpreter_disabled_uses_conservative_fallback():
    run_case_interpreter_disabled_uses_fallback()


def test_general_message_asks_one_question():
    run_case_general_message_asks_one_question()


def test_fallback_exact_code_searches_catalog():
    run_case_fallback_exact_code_searches_catalog()


# ============================================================
# EJECUCIÓN MANUAL
# ============================================================

def main():
    print("=" * 70)
    print("NIA OPENAI INTENT INTERPRETER TEST")
    print("=" * 70)

    run_case_fallback_air_speed_need()
    run_case_interpreter_disabled_uses_fallback()
    run_case_general_message_asks_one_question()
    run_case_fallback_exact_code_searches_catalog()

    print("\nFIN TEST OPENAI INTENT INTERPRETER ✅")


if __name__ == "__main__":
    main()