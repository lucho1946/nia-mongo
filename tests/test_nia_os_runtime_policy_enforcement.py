# ============================================================
# tests/test_nia_os_runtime_policy_enforcement.py
# ============================================================
# OBJETIVO:
# Validar que NIA OS runtime policy no solo audita,
# sino que puede corregir respuestas con demasiadas preguntas.
#
# Regla activa:
# - max_questions_per_turn = 1
# ============================================================

import json

from knowledge.nia_os_loader import build_nia_os_context
from orchestration.nia_os_runtime_policy import (
    count_questions_in_text,
    limit_response_to_max_questions,
    enforce_response_against_runtime_policy,
    evaluate_response_against_runtime_policy,
)


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


def run_case_limit_text_to_one_question():
    print_section("CASO 1: limitar texto a una pregunta")

    original = (
        "Para ayudarte mejor, ¿qué producto necesitas? "
        "¿Qué marca prefieres? "
        "¿Qué rango necesitas?"
    )

    cleaned = limit_response_to_max_questions(
        original,
        max_questions=1,
    )

    show_json("LIMIT RESULT", {
        "original": original,
        "cleaned": cleaned,
        "question_count": count_questions_in_text(cleaned),
    })

    assert_condition(
        count_questions_in_text(cleaned) == 1,
        "El texto corregido debe conservar solo una pregunta.",
    )

    assert_condition(
        "¿qué producto necesitas?" in cleaned.lower(),
        "Debe conservar la primera pregunta.",
    )

    assert_condition(
        "marca prefieres" not in cleaned.lower(),
        "Debe eliminar la segunda pregunta.",
    )


def run_case_enforce_response():
    print_section("CASO 2: enforcement sobre response dict")

    nia_os_context = build_nia_os_context("producto")

    response = {
        "intent": "producto",
        "response": (
            "Para ayudarte mejor, ¿qué producto necesitas? "
            "¿Qué marca prefieres? "
            "¿Qué rango necesitas?"
        ),
    }

    before = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    fixed_response = enforce_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    after = evaluate_response_against_runtime_policy(
        response=fixed_response,
        nia_os_context=nia_os_context,
    )

    show_json("ENFORCEMENT RESULT", {
        "before": before,
        "fixed_response": fixed_response,
        "after": after,
    })

    assert_condition(
        before.get("ok") is False,
        "Antes del enforcement debe fallar.",
    )

    assert_condition(
        after.get("ok") is True,
        "Después del enforcement debe cumplir.",
    )

    assert_condition(
        fixed_response.get("nia_os_runtime_enforcement", {}).get("applied") is True,
        "Debe marcar enforcement aplicado.",
    )

    assert_condition(
        count_questions_in_text(fixed_response.get("response")) == 1,
        "La respuesta final debe tener una sola pregunta.",
    )


def run_case_no_enforcement_needed():
    print_section("CASO 3: no modifica respuesta válida")

    nia_os_context = build_nia_os_context("producto")

    response = {
        "intent": "producto",
        "response": "Para continuar, ¿me confirmas la referencia del producto?",
    }

    fixed_response = enforce_response_against_runtime_policy(
        response=response.copy(),
        nia_os_context=nia_os_context,
    )

    show_json("NO ENFORCEMENT RESULT", fixed_response)

    assert_condition(
        fixed_response.get("response") == response.get("response"),
        "No debe modificar una respuesta válida.",
    )

    assert_condition(
        fixed_response.get("nia_os_runtime_enforcement", {}).get("applied") is False,
        "No debe aplicar enforcement si no hace falta.",
    )


def main():
    print("=" * 70)
    print("NIA OS RUNTIME POLICY ENFORCEMENT TEST")
    print("=" * 70)

    run_case_limit_text_to_one_question()
    run_case_enforce_response()
    run_case_no_enforcement_needed()

    print("\nFIN TEST NIA OS RUNTIME POLICY ENFORCEMENT ✅")


if __name__ == "__main__":
    main()