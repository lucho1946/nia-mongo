# ============================================================
# tests/test_semantic_need_profiles.py
# ============================================================
# OBJETIVO:
# Validar la capa de perfiles semánticos.
#
# No usa Mongo.
# No usa OpenAI.
# No consume tokens.
# ============================================================

import json

from knowledge.semantic_need_profiles import (
    resolve_semantic_need_profile,
    filter_results_for_interpreted_need,
    get_semantic_profile_debug,
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


def run_case_resolve_air_speed_profile():
    print_section("CASO 1: resolver perfil velocidad_aire")

    interpretation = {
        "normalized_query": "anemómetro medidor velocidad aire ductos ventilación",
        "semantic_profile": "velocidad_aire",
        "family_hint": "medicion",
        "subtype_hint": "velocidad_aire",
        "technical_signals": ["velocidad del aire", "ductos"],
    }

    profile = resolve_semantic_need_profile(interpretation)
    debug = get_semantic_profile_debug(interpretation)

    show_json("PROFILE DEBUG", debug)

    assert_condition(profile is not None, "Debe resolver un perfil.")
    assert_condition(
        profile.get("profile_id") == "velocidad_aire",
        "Debe resolver velocidad_aire.",
    )


def run_case_filter_false_positives():
    print_section("CASO 2: filtrar falsos positivos")

    interpretation = {
        "normalized_query": "anemómetro medidor velocidad aire ductos ventilación",
        "semantic_profile": "velocidad_aire",
        "family_hint": "medicion",
        "subtype_hint": "velocidad_aire",
        "positive_terms": [
            "anemómetro",
            "velocidad del aire",
            "ductos",
            "ventilación",
            "filtro de aire",
        ],
        "negative_terms": [
            "agua",
            "autos",
            "radar",
            "gasolina",
            "metales",
        ],
    }

    results = [
        {
            "codigo": "P161954",
            "nombre": "Medidor para agua tipo velocidad chorro unico",
            "nivel_1": "medidores-para-agua",
            "nivel_2": "Medidores para agua de velocidad",
        },
        {
            "codigo": "P233118",
            "nombre": "Medidor de velocidad de autos portátil",
            "nivel_1": "medidores-radares-de-velocidad",
            "nivel_2": "radares de velocidad moviles",
        },
        {
            "codigo": "P105051",
            "nombre": "Medidor de filtro de aire de manómetro inclinado serie 250-AF",
            "nivel_1": "manometros-de-columna-de-liquido",
            "nivel_2": "manometros de columna de liquido velocidad del aire",
        },
        {
            "codigo": "P999999",
            "nombre": "Anemómetro digital portátil para ductos",
            "nivel_1": "instrumentos-de-medicion",
            "nivel_2": "velocidad del aire",
        },
    ]

    filtered = filter_results_for_interpreted_need(
        results=results,
        interpretation=interpretation,
        max_items=10,
    )

    show_json("FILTERED RESULTS", filtered)

    codes = [item.get("codigo") for item in filtered]

    assert_condition("P161954" not in codes, "No debe incluir medidores de agua.")
    assert_condition("P233118" not in codes, "No debe incluir radares/autos.")
    assert_condition("P105051" in codes, "Debe incluir productos de aire.")
    assert_condition("P999999" in codes, "Debe incluir anemómetros.")


def run_case_without_profile_does_not_filter():
    print_section("CASO 3: sin perfil no filtra agresivamente")

    interpretation = {
        "normalized_query": "producto industrial general",
        "technical_signals": [],
    }

    results = [
        {"codigo": "A", "nombre": "Producto A"},
        {"codigo": "B", "nombre": "Producto B"},
    ]

    filtered = filter_results_for_interpreted_need(
        results=results,
        interpretation=interpretation,
        max_items=10,
    )

    show_json("NO PROFILE RESULTS", filtered)

    assert_condition(
        len(filtered) == 2,
        "Si no hay perfil, debe devolver resultados originales.",
    )


def main():
    print("=" * 70)
    print("NIA SEMANTIC NEED PROFILES TEST")
    print("=" * 70)

    run_case_resolve_air_speed_profile()
    run_case_filter_false_positives()
    run_case_without_profile_does_not_filter()

    print("\nFIN TEST SEMANTIC NEED PROFILES ✅")


if __name__ == "__main__":
    main()