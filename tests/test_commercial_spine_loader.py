# ============================================================
# test_commercial_spine_loader.py
# ============================================================
# Prueba formal de carga del proceso comercial maestro de NIA OS.
#
# Objetivo:
# - Validar que el loader cargue procesos desde:
#   knowledge/nia_os/processes/
# - Validar que process_commercial_spine_v1.json exista.
# - Validar que tenga las secciones mÃ­nimas necesarias.
# - Validar que el flujo maestro tenga estados comerciales clave.
#
# Esta prueba NO ejecuta todavÃ­a el flujo comercial.
# Solo valida que el proceso quede integrado como conocimiento formal.
# ============================================================

from __future__ import annotations

import json
from typing import Any, Dict, List

from knowledge.nia_os_loader import (
    validate_nia_os_files,
    get_available_processes,
    get_process,
    get_commercial_spine_process,
    build_nia_os_context,
)


COMMERCIAL_SPINE_ID = "process_commercial_spine_v1"


def assert_condition(condition: bool, message: str) -> None:
    """
    Assertion simple con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def get_state_names(master_flow: List[Dict[str, Any]]) -> List[str]:
    """
    Extrae los nombres de estados del master_flow.
    """
    states: List[str] = []

    for step in master_flow:
        if isinstance(step, dict) and step.get("state"):
            states.append(str(step["state"]))

    return states


def main() -> None:
    print("\n" + "=" * 70)
    print("NIA COMMERCIAL SPINE LOADER TEST")
    print("=" * 70)

    # ========================================================
    # 1. ValidaciÃ³n general de NIA OS
    # ========================================================

    validation = validate_nia_os_files()

    print("\nVALIDACIÃ“N NIA OS:")
    print(json.dumps(validation, ensure_ascii=False, indent=2, default=str))

    assert_condition(
        validation.get("ok") is True,
        f"La validaciÃ³n NIA OS debe estar OK. Errores: {validation.get('errors')}",
    )

    assert_condition(
        validation.get("commercial_spine_loaded") is True,
        "El commercial spine debe estar cargado.",
    )

    assert_condition(
        validation.get("process_count", 0) >= 1,
        "Debe existir al menos un proceso cargado.",
    )

    # ========================================================
    # 2. Procesos disponibles
    # ========================================================

    processes = get_available_processes()

    print("\nPROCESOS DISPONIBLES:")
    for process in processes:
        print(
            "-",
            process.get("process_id"),
            "|",
            process.get("name"),
            "|",
            process.get("version"),
        )

    assert_condition(
        isinstance(processes, list),
        "get_available_processes() debe devolver una lista.",
    )

    assert_condition(
        any(process.get("process_id") == COMMERCIAL_SPINE_ID for process in processes),
        f"Debe existir el proceso {COMMERCIAL_SPINE_ID}.",
    )

    # ========================================================
    # 3. Carga por ID
    # ========================================================

    process_by_id = get_process(COMMERCIAL_SPINE_ID)

    assert_condition(
        isinstance(process_by_id, dict),
        "get_process(process_commercial_spine_v1) debe devolver un dict.",
    )

    assert_condition(
        process_by_id.get("process_id") == COMMERCIAL_SPINE_ID,
        "El process_id cargado por get_process no coincide.",
    )

    # ========================================================
    # 4. Carga helper especÃ­fica del spine
    # ========================================================

    spine = get_commercial_spine_process()

    print("\nCOMMERCIAL SPINE:")
    print("process_id:", spine.get("process_id"))
    print("name:", spine.get("name"))
    print("version:", spine.get("version"))
    print("purpose:", spine.get("purpose"))

    assert_condition(
        isinstance(spine, dict),
        "get_commercial_spine_process() debe devolver un dict.",
    )

    assert_condition(
        spine.get("process_id") == COMMERCIAL_SPINE_ID,
        "El commercial spine debe tener el process_id correcto.",
    )

    # ========================================================
    # 5. Claves mÃ­nimas requeridas
    # ========================================================

    required_keys = [
        "process_id",
        "name",
        "version",
        "purpose",
        "important_note",
        "existing_modules_used",
        "golden_rules",
        "master_flow",
        "minimal_memory_fields",
        "response_policy",
        "recommended_location",
    ]

    for key in required_keys:
        assert_condition(
            key in spine,
            f"El commercial spine debe contener la clave requerida: {key}",
        )

    # ========================================================
    # 6. Reglas de oro
    # ========================================================

    golden_rules = spine.get("golden_rules", [])

    print("\nREGLAS DE ORO:")
    for rule in golden_rules:
        print("-", rule)

    assert_condition(
        isinstance(golden_rules, list) and len(golden_rules) >= 5,
        "golden_rules debe ser una lista con reglas comerciales.",
    )

    assert_condition(
        any("memoria" in str(rule).lower() or "contexto" in str(rule).lower() for rule in golden_rules),
        "golden_rules debe incluir regla de memoria/contexto.",
    )

    assert_condition(
        any("no inventar" in str(rule).lower() for rule in golden_rules),
        "golden_rules debe incluir regla de no inventar.",
    )

    # ========================================================
    # 7. Master flow
    # ========================================================

    master_flow = spine.get("master_flow", [])

    assert_condition(
        isinstance(master_flow, list),
        "master_flow debe ser una lista.",
    )

    assert_condition(
        len(master_flow) >= 10,
        "master_flow debe contener suficientes pasos del proceso comercial.",
    )

    states = get_state_names(master_flow)

    print("\nESTADOS DEL MASTER FLOW:")
    for state in states:
        print("-", state)

    required_states = [
        "cliente_escribe",
        "leer_contexto",
        "clasificar_intencion",
        "validar_necesidad_clara",
        "buscar_validar_producto",
        "producto_identificado",
        "preparar_cotizacion",
        "pedir_datos_faltantes_cotizacion",
        "cotizacion_lista_para_asesor",
        "preparar_proforma",
        "rediagnostico_o_alternativa",
        "seguimiento",
        "esperar_respuesta_cliente",
    ]

    for state in required_states:
        assert_condition(
            state in states,
            f"El master_flow debe contener el estado: {state}",
        )

    # ========================================================
    # 8. Campos mÃ­nimos de memoria
    # ========================================================

    minimal_memory_fields = spine.get("minimal_memory_fields", {})

    assert_condition(
        isinstance(minimal_memory_fields, dict),
        "minimal_memory_fields debe ser un objeto.",
    )

    for section in ["cliente", "producto_activo", "comercial"]:
        assert_condition(
            section in minimal_memory_fields,
            f"minimal_memory_fields debe contener la secciÃ³n: {section}",
        )

        assert_condition(
            isinstance(minimal_memory_fields[section], list),
            f"minimal_memory_fields.{section} debe ser una lista.",
        )

    cliente_fields = minimal_memory_fields.get("cliente", [])
    comercial_fields = minimal_memory_fields.get("comercial", [])

    assert_condition(
        "nombre" in cliente_fields,
        "minimal_memory_fields.cliente debe incluir nombre.",
    )

    assert_condition(
        "empresa" in cliente_fields,
        "minimal_memory_fields.cliente debe incluir empresa.",
    )

    assert_condition(
        "correo" in cliente_fields,
        "minimal_memory_fields.cliente debe incluir correo.",
    )

    assert_condition(
        "estado_negociacion" in comercial_fields,
        "minimal_memory_fields.comercial debe incluir estado_negociacion.",
    )

    assert_condition(
        "siguiente_paso" in comercial_fields,
        "minimal_memory_fields.comercial debe incluir siguiente_paso.",
    )

    # ========================================================
    # 9. PolÃ­tica de respuesta
    # ========================================================

    response_policy = spine.get("response_policy", {})

    assert_condition(
        isinstance(response_policy, dict),
        "response_policy debe ser un objeto.",
    )

    assert_condition(
        response_policy.get("max_questions_per_turn") == 1,
        "response_policy.max_questions_per_turn debe ser 1.",
    )

    assert_condition(
        response_policy.get("must_use_memory_before_asking") is True,
        "response_policy debe exigir usar memoria antes de preguntar.",
    )

    assert_condition(
        response_policy.get("must_not_repeat_existing_data") is True,
        "response_policy debe exigir no repetir datos existentes.",
    )

    assert_condition(
        response_policy.get("must_not_invent_commercial_information") is True,
        "response_policy debe exigir no inventar informaciÃ³n comercial.",
    )

    # ========================================================
    # 10. build_nia_os_context debe incluir commercial_spine
    # ========================================================

    nia_os_context = build_nia_os_context("comercial")

    assert_condition(
        isinstance(nia_os_context, dict),
        "build_nia_os_context debe devolver dict.",
    )

    assert_condition(
        "commercial_spine" in nia_os_context,
        "build_nia_os_context debe incluir commercial_spine.",
    )

    assert_condition(
        nia_os_context["commercial_spine"].get("process_id") == COMMERCIAL_SPINE_ID,
        "commercial_spine dentro de build_nia_os_context debe ser el proceso correcto.",
    )

    print("\nFIN TEST COMMERCIAL SPINE LOADER âœ…")


if __name__ == "__main__":
    main()

