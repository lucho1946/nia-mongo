# ============================================================
# tests/test_nia_os_diagnostic_context.py
# ============================================================
# OBJETIVO:
# Validar el contexto operativo de NIA OS por intención.
#
# Este test NO cambia el comportamiento de NIA.
# Este test NO expone información al usuario final.
# Solo nos ayuda a confirmar que los JSON de NIA OS están
# cargando correctamente y que cada intención activa los módulos
# esperados.
#
# Uso:
# - diagnóstico interno;
# - integración progresiva de NIA OS;
# - validación antes de conectar más reglas al orquestador.
# ============================================================

import json

from knowledge.nia_os_loader import (
    validate_nia_os_files,
    build_nia_os_context,
    get_module_ids_for_intent,
    get_commercial_spine_process,
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


def summarize_context(context: dict) -> dict:
    """
    Resume el contexto para que el log sea legible.
    No imprimimos todos los módulos completos para evitar ruido.
    """
    commercial_spine = context.get("commercial_spine") or {}

    return {
        "input_intent": context.get("input_intent"),
        "nia_os_intent": context.get("nia_os_intent"),
        "module_ids": context.get("module_ids", []),
        "module_count": len(context.get("modules", [])),
        "guardrails_count": len(context.get("guardrails", [])),
        "memory_rules_count": len(context.get("memory_rules", [])),
        "api_product_rules_keys": list((context.get("api_product_rules") or {}).keys()),
        "technical_product_rules_keys": list((context.get("technical_product_rules") or {}).keys()),
        "commercial_spine": {
            "process_id": commercial_spine.get("process_id"),
            "name": commercial_spine.get("name"),
            "version": commercial_spine.get("version"),
            "has_master_flow": bool(commercial_spine.get("master_flow")),
            "has_response_policy": bool(commercial_spine.get("response_policy")),
        },
    }


def run_case_validate_loader():
    print_section("CASO 1: validar archivos NIA OS")

    validation = validate_nia_os_files()

    show_json("NIA OS VALIDATION", validation)

    assert_condition(
        validation.get("ok") is True,
        f"NIA OS debe validar sin errores. Errores: {validation.get('errors')}",
    )

    assert_condition(
        validation.get("module_count", 0) > 0,
        "Debe existir al menos un módulo NIA OS cargado.",
    )

    assert_condition(
        validation.get("commercial_spine_loaded") is True,
        "Debe cargar el proceso commercial_spine.",
    )


def run_case_context_by_intent(intent: str, expected_modules: list[str]):
    print_section(f"CASO INTENT: {intent}")

    module_ids = get_module_ids_for_intent(intent)
    context = build_nia_os_context(intent)

    show_json("NIA OS CONTEXT SUMMARY", summarize_context(context))

    assert_condition(
        context.get("input_intent") == intent,
        f"Debe conservar input_intent={intent}.",
    )

    assert_condition(
        isinstance(module_ids, list),
        "module_ids debe ser lista.",
    )

    assert_condition(
        len(module_ids) > 0,
        f"Intent {intent} debe activar al menos un módulo.",
    )

    assert_condition(
        context.get("module_ids") == module_ids,
        "El contexto debe conservar los module_ids del loader.",
    )

    for expected_module in expected_modules:
        assert_condition(
            expected_module in module_ids,
            f"Intent {intent} debe incluir módulo esperado: {expected_module}",
        )

    assert_condition(
        len(context.get("modules", [])) == len(module_ids),
        "Debe cargar el detalle de todos los módulos activos.",
    )

    assert_condition(
        len(context.get("guardrails", [])) > 0,
        "El contexto debe incluir guardrails.",
    )

    assert_condition(
        isinstance(context.get("commercial_spine"), dict),
        "El contexto debe incluir commercial_spine.",
    )

    assert_condition(
        bool(context.get("commercial_spine", {}).get("process_id")),
        "commercial_spine debe tener process_id.",
    )


def run_case_commercial_spine():
    print_section("CASO 2: commercial spine cargado")

    process = get_commercial_spine_process()

    show_json("COMMERCIAL SPINE SUMMARY", {
        "process_id": process.get("process_id"),
        "name": process.get("name"),
        "version": process.get("version"),
        "purpose": process.get("purpose"),
        "master_flow_type": type(process.get("master_flow")).__name__,
        "golden_rules_count": len(process.get("golden_rules", [])),
        "minimal_memory_fields_count": len(process.get("minimal_memory_fields", [])),
        "response_policy_type": type(process.get("response_policy")).__name__,
    })

    assert_condition(
        process.get("process_id") == "process_commercial_spine_v1",
        "Debe cargar process_commercial_spine_v1.",
    )

    assert_condition(
        bool(process.get("master_flow")),
        "Commercial spine debe tener master_flow.",
    )

    assert_condition(
        bool(process.get("golden_rules")),
        "Commercial spine debe tener golden_rules.",
    )

    assert_condition(
        bool(process.get("response_policy")),
        "Commercial spine debe tener response_policy.",
    )


def main():
    print("=" * 70)
    print("NIA OS DIAGNOSTIC CONTEXT TEST")
    print("=" * 70)

    run_case_validate_loader()

    run_case_context_by_intent(
        "saludo",
        expected_modules=[
            "module_motor_comercial",
            "module_guardrails_no_inventar",
        ],
    )

    run_case_context_by_intent(
        "codigo_producto",
        expected_modules=[
            "module_motor_comercial",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_guardrails_no_inventar",
        ],
    )

    run_case_context_by_intent(
        "producto",
        expected_modules=[
            "module_motor_comercial",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_guardrails_no_inventar",
        ],
    )

    run_case_context_by_intent(
        "comercial",
        expected_modules=[
            "module_motor_comercial",
            "module_guardrails_no_inventar",
        ],
    )

    run_case_context_by_intent(
        "general",
        expected_modules=[
            "module_motor_comercial",
            "module_guardrails_no_inventar",
        ],
    )

    run_case_commercial_spine()

    print("\nFIN TEST NIA OS DIAGNOSTIC CONTEXT ✅")


if __name__ == "__main__":
    main()