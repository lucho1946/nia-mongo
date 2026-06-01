# ============================================================
# tests/test_nia_os_intent_module_matrix.py
# ============================================================
# OBJETIVO:
# Validar la matriz intención -> módulos NIA OS.
#
# Este test valida:
# - que los intents locales del proyecto se mapean correctamente;
# - que los intents propios de NIA OS cargan sus módulos;
# - que cada intención tiene guardrails;
# - que no existen módulos declarados pero no cargables;
# - que los módulos críticos aparecen donde deben aparecer.
#
# Este test NO prueba conversación completa.
# Este test protege la capa:
#
# intent_router / intent NIA OS
#   -> knowledge/nia_os/router/intent_module_map.json
#   -> knowledge/nia_os/modules/*.json
#
# Alineación:
# Antes de conectar más conocimiento al response engine,
# primero validamos módulo por módulo para evitar respuestas inventadas
# o flujos comerciales desordenados.
# ============================================================

import json

from knowledge.nia_os_loader import (
    validate_nia_os_files,
    get_module_ids_for_intent,
    get_modules_for_intent,
    get_module,
    load_intent_module_map,
    LOCAL_TO_NIA_OS_INTENT,
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


def assert_contains_all(
    actual_items: list[str],
    expected_items: list[str],
    message_prefix: str,
):
    """
    Valida que actual_items contenga todos los expected_items.
    """
    missing = [
        item
        for item in expected_items
        if item not in actual_items
    ]

    assert_condition(
        not missing,
        f"{message_prefix}. Faltan módulos: {missing}. Actual: {actual_items}",
    )


def assert_no_duplicates(items: list[str], message: str):
    """
    Evita módulos duplicados dentro de una intención.
    """
    assert_condition(
        len(items) == len(set(items)),
        f"{message}. Hay duplicados en: {items}",
    )


# ============================================================
# MATRIZ ESPERADA
# ============================================================

LOCAL_INTENT_EXPECTATIONS = {
    # Intent producido por nuestro intent_router:
    # saludo -> intent NIA OS saludo.
    "saludo": {
        "nia_os_intent": "saludo",
        "must_include": [
            "module_motor_comercial",
            "module_guardrails_no_inventar",
        ],
    },

    # Intent local para código exacto:
    # codigo_producto -> consulta_producto_codigo.
    "codigo_producto": {
        "nia_os_intent": "consulta_producto_codigo",
        "must_include": [
            "module_motor_comercial",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_guardrails_no_inventar",
            "module_observabilidad",
        ],
    },

    # Intent local para búsqueda por descripción:
    # producto -> consulta_producto_descripcion.
    "producto": {
        "nia_os_intent": "consulta_producto_descripcion",
        "must_include": [
            "module_motor_comercial",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_guardrails_no_inventar",
            "module_observabilidad",
        ],
    },

    # Intent local comercial:
    # comercial -> pide_precio.
    "comercial": {
        "nia_os_intent": "pide_precio",
        "must_include": [
            "module_motor_comercial",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_motor_cotizacion_precio",
            "module_guardrails_no_inventar",
        ],
    },

    # Intent general/default:
    # general -> default.
    "general": {
        "nia_os_intent": "default",
        "must_include": [
            "module_motor_comercial",
            "module_guardrails_no_inventar",
            "module_memoria_contextual",
            "module_estado_negociacion",
        ],
    },
}


DIRECT_NIA_OS_INTENT_EXPECTATIONS = {
    "archivo_recibido": {
        "must_include": [
            "module_vision_archivos",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_motor_comercial",
            "module_guardrails_no_inventar",
            "module_hibrido_humano_ia",
            "module_observabilidad",
        ],
    },
    "foto_producto": {
        "must_include": [
            "module_vision_archivos",
            "module_motor_tecnico_producto",
            "module_motor_api_productos",
            "module_motor_comercial",
            "module_guardrails_no_inventar",
            "module_hibrido_humano_ia",
            "module_observabilidad",
        ],
    },
    "pide_ficha_tecnica": {
        "must_include": [
            "module_motor_tecnico_producto",
            "module_motor_soporte_tecnico",
            "module_vision_archivos",
            "module_guardrails_no_inventar",
        ],
    },
    "quiere_comprar": {
        "must_include": [
            "module_motor_comercial",
            "module_motor_cierre_proforma",
            "module_guardrails_no_inventar",
            "module_memoria_contextual",
            "module_estado_negociacion",
        ],
    },
    "objecion_precio": {
        "must_include": [
            "module_motor_comercial",
            "module_motor_cotizacion_precio",
            "module_guardrails_no_inventar",
        ],
    },
    "default": {
        "must_include": [
            "module_motor_comercial",
            "module_guardrails_no_inventar",
            "module_memoria_contextual",
            "module_estado_negociacion",
        ],
    },
}


# ============================================================
# CASO 1
# Validación general de archivos NIA OS
# ============================================================

def run_case_validate_nia_os_files():
    print_section("CASO 1: validación general de archivos NIA OS")

    validation = validate_nia_os_files()

    show_json("VALIDACIÓN NIA OS", validation)

    assert_condition(
        validation.get("ok") is True,
        f"NIA OS debe validar ok=True. Errores: {validation.get('errors')}",
    )

    assert_condition(
        validation.get("module_count", 0) >= 1,
        "Debe existir al menos un módulo cargado.",
    )

    assert_condition(
        validation.get("commercial_spine_loaded") is True,
        "Debe estar cargado process_commercial_spine_v1.",
    )


# ============================================================
# CASO 2
# Intents locales -> intents NIA OS -> módulos esperados
# ============================================================

def run_case_local_intents_matrix():
    print_section("CASO 2: matriz intents locales -> módulos NIA OS")

    show_json("LOCAL_TO_NIA_OS_INTENT", LOCAL_TO_NIA_OS_INTENT)

    for local_intent, expectation in LOCAL_INTENT_EXPECTATIONS.items():
        expected_nia_os_intent = expectation["nia_os_intent"]
        module_ids = get_module_ids_for_intent(local_intent)

        print_section(f"Intent local: {local_intent}")
        print("NIA OS intent esperado:", expected_nia_os_intent)
        print("Módulos:", module_ids)

        assert_condition(
            LOCAL_TO_NIA_OS_INTENT.get(local_intent) == expected_nia_os_intent,
            (
                f"El intent local {local_intent} debe mapear a "
                f"{expected_nia_os_intent}."
            ),
        )

        assert_no_duplicates(
            module_ids,
            f"El intent local {local_intent} no debe tener módulos duplicados",
        )

        assert_contains_all(
            module_ids,
            expectation["must_include"],
            f"El intent local {local_intent} no cargó los módulos esperados",
        )

        assert_condition(
            "module_guardrails_no_inventar" in module_ids,
            f"El intent local {local_intent} debe tener guardrails.",
        )

        modules = get_modules_for_intent(local_intent)

        assert_condition(
            len(modules) == len(module_ids),
            (
                f"Todos los module_ids de {local_intent} deben cargar módulo. "
                f"module_ids={len(module_ids)} modules={len(modules)}"
            ),
        )


# ============================================================
# CASO 3
# Intents directos NIA OS
# ============================================================

def run_case_direct_nia_os_intents_matrix():
    print_section("CASO 3: matriz intents directos NIA OS")

    intent_map = load_intent_module_map()

    show_json("INTENT MODULE MAP", intent_map)

    for nia_os_intent, expectation in DIRECT_NIA_OS_INTENT_EXPECTATIONS.items():
        module_ids = get_module_ids_for_intent(nia_os_intent)

        print_section(f"Intent NIA OS: {nia_os_intent}")
        print("Módulos:", module_ids)

        assert_condition(
            nia_os_intent in intent_map,
            f"El intent NIA OS {nia_os_intent} debe existir en intent_module_map.",
        )

        assert_no_duplicates(
            module_ids,
            f"El intent NIA OS {nia_os_intent} no debe tener módulos duplicados",
        )

        assert_contains_all(
            module_ids,
            expectation["must_include"],
            f"El intent NIA OS {nia_os_intent} no cargó los módulos esperados",
        )

        assert_condition(
            "module_guardrails_no_inventar" in module_ids,
            f"El intent NIA OS {nia_os_intent} debe tener guardrails.",
        )

        modules = get_modules_for_intent(nia_os_intent)

        assert_condition(
            len(modules) == len(module_ids),
            (
                f"Todos los module_ids de {nia_os_intent} deben cargar módulo. "
                f"module_ids={len(module_ids)} modules={len(modules)}"
            ),
        )


# ============================================================
# CASO 4
# Cada módulo declarado debe ser cargable por ID
# ============================================================

def run_case_all_declared_modules_are_loadable():
    print_section("CASO 4: todos los módulos declarados son cargables")

    intent_map = load_intent_module_map()

    all_module_ids = sorted({
        module_id
        for module_ids in intent_map.values()
        for module_id in module_ids
    })

    print("Módulos únicos declarados:", all_module_ids)

    for module_id in all_module_ids:
        module = get_module(module_id)

        assert_condition(
            isinstance(module, dict),
            f"El módulo {module_id} debe cargar como dict.",
        )

        assert_condition(
            module.get("module_id") == module_id,
            (
                f"El módulo {module_id} debe tener module_id interno igual. "
                f"Encontrado: {module.get('module_id')}"
            ),
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA OS INTENT MODULE MATRIX TEST")
    print("=" * 70)

    run_case_validate_nia_os_files()
    run_case_local_intents_matrix()
    run_case_direct_nia_os_intents_matrix()
    run_case_all_declared_modules_are_loadable()

    print("\nFIN TEST NIA OS INTENT MODULE MATRIX ✅")


if __name__ == "__main__":
    main()