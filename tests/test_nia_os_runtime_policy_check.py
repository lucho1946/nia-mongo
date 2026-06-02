# ============================================================
# tests/test_nia_os_runtime_policy_check.py
# ============================================================
# OBJETIVO:
# Validar que NIA OS runtime_policy ya no solo se adjunta
# como metadata, sino que también evalúa la respuesta final.
#
# Primera regla auditada:
# - max_questions_per_turn = 1
# ============================================================

import json

from knowledge.nia_os_loader import build_nia_os_context
from orchestration.nia_os_runtime_policy import (
    count_questions_in_text,
    evaluate_response_against_runtime_policy,
    has_next_step_signal,
    detect_repeated_existing_data_request,
)
from orchestration.nia_orchestrator import process_message


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


def run_case_count_questions():
    print_section("CASO 1: contar preguntas")

    assert_condition(
        count_questions_in_text("Hola, ¿qué producto necesitas?") == 1,
        "Debe contar una pregunta.",
    )

    assert_condition(
        count_questions_in_text("¿Qué producto necesitas? ¿Qué marca buscas?") == 2,
        "Debe contar dos preguntas.",
    )

    assert_condition(
        count_questions_in_text("Encontré el producto exacto.") == 0,
        "Debe contar cero preguntas.",
    )
    assert_condition(
        has_next_step_signal("Hola, soy NIA. ¿Qué producto industrial necesitas?") is True,
        "El saludo debe contar como siguiente paso comercial claro.",
    )


def run_case_policy_allows_one_question():
    print_section("CASO 2: política permite una pregunta")

    nia_os_context = build_nia_os_context("producto")

    response = {
        "response": "Para continuar con la cotización, ¿me confirmas nombre, empresa y correo?"
    }

    result = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    show_json("POLICY CHECK ONE QUESTION", result)

    assert_condition(
        result.get("ok") is True,
        "Una pregunta debe ser permitida.",
    )

    assert_condition(
        result.get("question_count") == 1,
        "Debe detectar una pregunta.",
    )

    assert_condition(
        result.get("recommendation") == "allow",
        "Debe recomendar allow.",
    )
    
    assert_condition(
        "must_include_next_step" in result.get("checked_rules", []),
        "Debe auditar must_include_next_step.",
    )

    assert_condition(
        result.get("includes_next_step") is True,
        "Debe detectar siguiente paso en la respuesta.",
    )


def run_case_policy_flags_multiple_questions():
    print_section("CASO 3: política detecta varias preguntas")

    nia_os_context = build_nia_os_context("producto")

    response = {
    "response": (
        "Para ayudarte mejor, ¿qué producto necesitas? "
        "¿Qué marca prefieres? "
        "¿Qué rango necesitas?"
    )
}

    result = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    show_json("POLICY CHECK MULTIPLE QUESTIONS", result)

    assert_condition(
        result.get("ok") is False,
        "Varias preguntas deben marcarse como riesgo.",
    )

    assert_condition(
        "too_many_questions_in_turn" in result.get("flags", []),
        "Debe marcar too_many_questions_in_turn.",
    )

    assert_condition(
        result.get("recommendation") == "review",
        "Debe recomendar review.",
    )


def run_case_orchestrator_attaches_policy_check():
    print_section("CASO 4: orquestador adjunta runtime_policy_check")

    response = process_message(
        message="Hola",
        canal="web",
        cliente_id="test_runtime_policy_check",
    )

    show_json("ORCHESTRATOR RESPONSE", response)

    nia_os = response.get("nia_os") or {}
    runtime_policy_check = nia_os.get("runtime_policy_check") or {}

    assert_condition(
        isinstance(runtime_policy_check, dict),
        "nia_os debe incluir runtime_policy_check.",
    )

    assert_condition(
        runtime_policy_check.get("source") == "nia_os_runtime_policy",
        "runtime_policy_check debe venir de nia_os_runtime_policy.",
    )

    assert_condition(
        "max_questions_per_turn" in runtime_policy_check.get("checked_rules", []),
        "Debe auditar max_questions_per_turn.",
    )

    assert_condition(
        runtime_policy_check.get("recommendation") in ["allow", "review"],
        "Debe devolver una recomendación válida.",
    )
    
def run_case_policy_flags_missing_next_step():
    print_section("CASO 5: política detecta falta de siguiente paso")

    nia_os_context = build_nia_os_context("producto")

    response = {
        "response": "Encontré información relacionada con el producto."
    }

    result = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    show_json("POLICY CHECK MISSING NEXT STEP", result)

    assert_condition(
        result.get("ok") is False,
        "Una respuesta sin siguiente paso debe marcarse como no ok.",
    )

    assert_condition(
        "missing_next_step" in result.get("flags", []),
        "Debe marcar missing_next_step.",
    )

    assert_condition(
        result.get("includes_next_step") is False,
        "Debe indicar que no hay siguiente paso.",
    )

def run_case_policy_flags_missing_next_step():
    print_section("CASO 5: política detecta falta de siguiente paso")

    nia_os_context = build_nia_os_context("producto")

    response = {
        "response": "Encontré información relacionada con el producto."
    }

    result = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    show_json("POLICY CHECK MISSING NEXT STEP", result)

    assert_condition(
        result.get("ok") is False,
        "Una respuesta sin siguiente paso debe marcarse como no ok.",
    )

    assert_condition(
        "missing_next_step" in result.get("flags", []),
        "Debe marcar missing_next_step.",
    )

    assert_condition(
        result.get("includes_next_step") is False,
        "Debe indicar que no hay siguiente paso.",
    )
    
def run_case_policy_flags_repeated_existing_data():
    print_section("CASO 6: política detecta datos ya existentes repetidos")

    nia_os_context = build_nia_os_context("comercial")

    response = {
        "response": (
            "Para continuar con la cotización, "
            "¿me confirmas nombre, empresa y correo?"
        ),
        "commercial_data": {
            "nombre_cliente": "Luis Diaz",
            "empresa": "Viaindustrial",
            "correo": "luis2004diazalzate@gmail.com",
        },
    }

    direct_check = detect_repeated_existing_data_request(response)

    result = evaluate_response_against_runtime_policy(
        response=response,
        nia_os_context=nia_os_context,
    )

    show_json("REPEATED DATA DIRECT CHECK", direct_check)
    show_json("POLICY CHECK REPEATED DATA", result)

    assert_condition(
        direct_check.get("has_repeated_existing_data_request") is True,
        "Debe detectar solicitud repetida de datos existentes.",
    )

    assert_condition(
        set(direct_check.get("repeated_fields", [])) == {"nombre", "empresa", "correo"},
        "Debe detectar nombre, empresa y correo repetidos.",
    )

    assert_condition(
        result.get("ok") is False,
        "La política debe marcar no ok si repite datos existentes.",
    )

    assert_condition(
        "must_not_repeat_existing_data" in result.get("checked_rules", []),
        "Debe auditar must_not_repeat_existing_data.",
    )

    assert_condition(
        "repeated_existing_data_request" in result.get("flags", []),
        "Debe marcar repeated_existing_data_request.",
    )

    repeated_data = result.get("repeated_existing_data") or {}

    assert_condition(
        set(repeated_data.get("repeated_fields", [])) == {"nombre", "empresa", "correo"},
        "El resultado debe conservar los campos repetidos.",
    )

def main():
    print("=" * 70)
    print("NIA OS RUNTIME POLICY CHECK TEST")
    print("=" * 70)

    run_case_count_questions()
    run_case_policy_allows_one_question()
    run_case_policy_flags_multiple_questions()
    run_case_orchestrator_attaches_policy_check()
    run_case_policy_flags_missing_next_step()
    run_case_policy_flags_repeated_existing_data()

    print("\nFIN TEST NIA OS RUNTIME POLICY CHECK ✅")
    
if __name__ == "__main__":
    main()