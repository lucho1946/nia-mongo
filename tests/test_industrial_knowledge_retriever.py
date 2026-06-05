# ============================================================
# tests/test_industrial_knowledge_retriever.py
# ============================================================
# OBJETIVO:
# Validar que el retriever de libros industriales puede cargar
# y buscar fragmentos técnicos desde book_rag_ready_all.jsonl.
#
# No llama OpenAI.
# No consulta MongoDB.
# No recomienda productos.
# ============================================================

import json
import sys
from pathlib import Path


# ============================================================
# BOOTSTRAP DE IMPORTS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from retrieval.industrial_knowledge_retriever import (  # noqa: E402
    build_industrial_context_for_prompt,
    load_industrial_book_records,
    search_industrial_knowledge,
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


def run_case_load_books():
    print_section("CASO 1: cargar libros industriales")

    records = load_industrial_book_records()

    print("TOTAL RECORDS:", len(records))

    assert_condition(
        isinstance(records, list),
        "Los registros deben cargarse como lista.",
    )

    assert_condition(
        len(records) > 0,
        "Debe cargar al menos un fragmento de libros industriales.",
    )

    first = records[0]

    assert_condition(
        isinstance(first, dict),
        "Cada registro debe ser un dict.",
    )

    assert_condition(
        "text" in first or "search_text" in first,
        "Cada registro debe tener text o search_text.",
    )


def run_case_search_instrumentation():
    print_section("CASO 2: buscar conocimiento de instrumentación")

    result = search_industrial_knowledge(
        "transmisor presión temperatura caudal nivel instrumentación",
        max_results=5,
    )

    show_json("INDUSTRIAL SEARCH RESULT", result)

    assert_condition(
        result.get("ok") is True,
        "La búsqueda debe responder ok=True.",
    )

    assert_condition(
        result.get("total_records", 0) > 0,
        "Debe haber registros cargados.",
    )

    assert_condition(
        result.get("result_count", 0) >= 1,
        "Debe encontrar al menos un fragmento relevante.",
    )

    first = result["results"][0]

    assert_condition(
        first.get("score", 0) > 0,
        "El primer resultado debe tener score positivo.",
    )

    assert_condition(
        first.get("excerpt"),
        "El primer resultado debe tener excerpt.",
    )


def run_case_build_prompt_context():
    print_section("CASO 3: construir contexto compacto para prompt")

    result = build_industrial_context_for_prompt(
        "medir velocidad del aire en ductos de ventilación",
        max_results=3,
        max_chars=2000,
    )

    show_json("INDUSTRIAL PROMPT CONTEXT", result)

    assert_condition(
        result.get("ok") is True,
        "Debe responder ok=True.",
    )

    assert_condition(
        "context" in result,
        "Debe devolver context.",
    )

    assert_condition(
        isinstance(result.get("context"), str),
        "context debe ser string.",
    )

    assert_condition(
        len(result.get("context", "")) <= 2000,
        "El contexto debe respetar max_chars.",
    )


# ============================================================
# TESTS PYTEST
# ============================================================

def test_load_books():
    run_case_load_books()


def test_search_instrumentation():
    run_case_search_instrumentation()


def test_build_prompt_context():
    run_case_build_prompt_context()


# ============================================================
# EJECUCIÓN MANUAL
# ============================================================

def main():
    print("=" * 70)
    print("NIA INDUSTRIAL KNOWLEDGE RETRIEVER TEST")
    print("=" * 70)

    run_case_load_books()
    run_case_search_instrumentation()
    run_case_build_prompt_context()

    print("\nFIN TEST INDUSTRIAL KNOWLEDGE RETRIEVER ✅")


if __name__ == "__main__":
    main()