# ============================================================
# tests/test_nia_os_runtime_policy.py
# ============================================================
# OBJETIVO:
# Validar que el orquestador pueda leer políticas runtime
# desde NIA OS commercial_spine.
#
# Este test no cambia el comportamiento público de NIA.
# Solo valida que el JSON ya puede convertirse en reglas
# ejecutables y seguras.
# ============================================================

import json

from knowledge.nia_os_loader import build_nia_os_context
from orchestration.nia_os_runtime_policy import (
    build_runtime_policy_from_nia_os,
    get_max_questions_per_turn,
    should_ask_question_this_turn,
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


def run_case_policy_from_commercial_spine():
    print_section("CASO 1: política runtime desde commercial_spine")

    nia_os_context = build_nia_os_context("producto")

    policy = build_runtime_policy_from_nia_os(nia_os_context)

    show_json("RUNTIME POLICY", policy)

    assert_condition(
        policy.get("source") == "nia_os_commercial_spine.response_policy",
        "Debe indicar fuente de política runtime.",
    )

    assert_condition(
        policy.get("max_questions_per_turn") == 1,
        "Debe leer max_questions_per_turn=1 desde NIA OS.",
    )

    assert_condition(
        policy.get("must_use_memory_before_asking") is True,
        "Debe respetar must_use_memory_before_asking=True.",
    )

    assert_condition(
        policy.get("must_include_next_step") is True,
        "Debe respetar must_include_next_step=True.",
    )

    assert_condition(
        policy.get("must_not_repeat_existing_data") is True,
        "Debe respetar must_not_repeat_existing_data=True.",
    )

    assert_condition(
        policy.get("must_not_invent_commercial_information") is True,
        "Debe respetar must_not_invent_commercial_information=True.",
    )


def run_case_max_questions_helper():
    print_section("CASO 2: helper max_questions_per_turn")

    nia_os_context = build_nia_os_context("comercial")

    max_questions = get_max_questions_per_turn(nia_os_context)

    show_json("MAX QUESTIONS", {
        "max_questions_per_turn": max_questions,
    })

    assert_condition(
        max_questions == 1,
        "El máximo de preguntas por turno debe ser 1.",
    )


def run_case_should_ask_question_this_turn():
    print_section("CASO 3: controlar preguntas por turno")

    nia_os_context = build_nia_os_context("producto")

    assert_condition(
        should_ask_question_this_turn(
            questions_to_ask_now=0,
            nia_os_context=nia_os_context,
        ) is True,
        "Si aún no preguntó en este turno, puede preguntar.",
    )

    assert_condition(
        should_ask_question_this_turn(
            questions_to_ask_now=1,
            nia_os_context=nia_os_context,
        ) is False,
        "Si ya hizo una pregunta en este turno, no debe agregar otra.",
    )


def run_case_defaults_are_safe():
    print_section("CASO 4: defaults seguros")

    policy = build_runtime_policy_from_nia_os({})

    show_json("DEFAULT POLICY", policy)

    assert_condition(
        policy.get("max_questions_per_turn") == 1,
        "Default debe mantener máximo 1 pregunta por turno.",
    )

    assert_condition(
        policy.get("must_not_invent_commercial_information") is True,
        "Default debe mantener no inventar información comercial.",
    )


def main():
    print("=" * 70)
    print("NIA OS RUNTIME POLICY TEST")
    print("=" * 70)

    run_case_policy_from_commercial_spine()
    run_case_max_questions_helper()
    run_case_should_ask_question_this_turn()
    run_case_defaults_are_safe()

    print("\nFIN TEST NIA OS RUNTIME POLICY ✅")


if __name__ == "__main__":
    main()