# ============================================================
# tests/test_response_guardrails.py
# ============================================================
# OBJETIVO:
# Validar el primer módulo activo de guardrails de respuesta.
#
# Este test valida:
# - respuestas seguras permitidas;
# - promesas riesgosas detectadas;
# - claims comerciales sin fuente marcados;
# - payloads con cards permitidos;
# - metadata response_guardrails adjuntada correctamente.
#
# Este test NO conecta todavía el módulo al orquestador.
# Primero validamos aislado para evitar romper NIA.
# ============================================================

import json

from knowledge.response_guardrails import (
    validate_response_guardrails,
    apply_response_guardrails,
    should_review_response,
    is_response_allowed,
)


# ============================================================
# UTILIDADES
# ============================================================

def print_section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def assert_condition(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def show_json(label: str, data):
    print_section(label)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ============================================================
# CASO 1
# Respuesta segura general
# ============================================================

def run_case_safe_general_response():
    print_section("CASO 1: respuesta general segura")

    result = validate_response_guardrails(
        "Hola, soy NIA. ¿Qué producto industrial necesitas?",
        source="test",
    )

    show_json("GUARDRAIL RESULT", result)

    assert_condition(result.get("ok") is True, "Debe ser ok=True.")
    assert_condition(result.get("risk_level") == "none", "Debe ser riesgo none.")
    assert_condition(result.get("recommendation") == "allow", "Debe permitir respuesta.")


# ============================================================
# CASO 2
# Producto respaldado por cards
# ============================================================

def run_case_product_response_with_cards():
    print_section("CASO 2: respuesta de producto con respaldo de cards")

    payload = {
        "response": (
            "Encontré el producto exacto: Anemometros digitales portatiles "
            "Indicadores | Marca: lutron | Código: 300203 | Precio: $480,393 COP "
            "| Disponible en Bogotá (6 und) · 1 DIAS"
        ),
        "cards": [
            {
                "codigo": "300203",
                "nombre": "Anemometros digitales portatiles Indicadores",
                "marca": "lutron",
                "precio": "$480,393 COP",
                "disponibilidad": "Disponible en Bogotá (6 und)",
            }
        ],
    }

    result_payload = apply_response_guardrails(payload, source="test")

    show_json("PAYLOAD CON GUARDRAILS", result_payload)

    guardrails = result_payload.get("response_guardrails")

    assert_condition(isinstance(guardrails, dict), "Debe adjuntar response_guardrails.")
    assert_condition(guardrails.get("recommendation") == "allow", "Debe permitir si hay card fuente.")
    assert_condition(is_response_allowed(result_payload) is True, "is_response_allowed debe ser True.")
    assert_condition(should_review_response(result_payload) is False, "No debe requerir revisión.")


# ============================================================
# CASO 3
# Promesa riesgosa
# ============================================================

def run_case_risky_promise_language():
    print_section("CASO 3: promesa riesgosa detectada")

    result = validate_response_guardrails(
        "Te garantizo entrega garantizada mañana y stock asegurado.",
        source="test",
    )

    show_json("GUARDRAIL RESULT", result)

    assert_condition(result.get("ok") is False, "Debe ser ok=False.")
    assert_condition(result.get("risk_level") == "high", "Debe ser riesgo high.")
    assert_condition(result.get("recommendation") == "review", "Debe requerir revisión.")
    assert_condition(
        "risky_promise_language" in result.get("flags", []),
        "Debe marcar risky_promise_language.",
    )


# ============================================================
# CASO 4
# Claim comercial sensible sin fuente
# ============================================================

def run_case_sensitive_claim_without_source():
    print_section("CASO 4: claim comercial sensible sin fuente")

    result = validate_response_guardrails(
        "El precio es $100.000 y hay stock disponible.",
        source="test",
    )

    show_json("GUARDRAIL RESULT", result)

    assert_condition(result.get("ok") is False, "Debe ser ok=False.")
    assert_condition(
        "sensitive_commercial_claim_without_product_source" in result.get("flags", []),
        "Debe marcar claim comercial sin fuente.",
    )
    assert_condition(result.get("recommendation") == "review", "Debe requerir revisión.")


# ============================================================
# CASO 5
# Lenguaje seguro de consulta/validación
# ============================================================

def run_case_safe_uncertainty_language():
    print_section("CASO 5: lenguaje seguro de validación")

    result = validate_response_guardrails(
        "Debo validar precio y disponibilidad con el catálogo real o con un asesor.",
        source="test",
    )

    show_json("GUARDRAIL RESULT", result)

    assert_condition(result.get("ok") is True, "Debe ser ok=True.")
    assert_condition(result.get("uses_safe_uncertainty") is True, "Debe detectar lenguaje seguro.")
    assert_condition(result.get("recommendation") == "allow", "Debe permitir respuesta.")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA RESPONSE GUARDRAILS TEST")
    print("=" * 70)

    run_case_safe_general_response()
    run_case_product_response_with_cards()
    run_case_risky_promise_language()
    run_case_sensitive_claim_without_source()
    run_case_safe_uncertainty_language()

    print("\nFIN TEST NIA RESPONSE GUARDRAILS ✅")


if __name__ == "__main__":
    main()