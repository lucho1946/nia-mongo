# ============================================================
# test_dynamic_questions.py
# ============================================================
# Prueba aislada del motor dinámico de preguntas.
# No toca Mongo.
# No toca retrieval.
# No toca orchestrator.
# ============================================================

from knowledge.dynamic_question_engine import (
    decide_next_step,
    decide_with_catalog_knowledge,
)


def print_result(title, result):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    print(result)


def run_tests():
    # --------------------------------------------------------
    # Caso 1: sin contexto suficiente
    # --------------------------------------------------------
    context_1 = {
        "familia": "sensor",
        "rango": None,
        "salida": None,
        "marca": None,
    }

    result_1 = decide_next_step(
        context=context_1,
        questions_asked=0,
        priority_fields=["rango", "salida", "marca"],
    )

    print_result("CASO 1 - Sensor sin rango", result_1)

    # --------------------------------------------------------
    # Caso 2: ya tiene rango, falta salida
    # --------------------------------------------------------
    context_2 = {
        "familia": "sensor",
        "rango": "0-10 bar",
        "salida": None,
        "marca": None,
    }

    result_2 = decide_next_step(
        context=context_2,
        questions_asked=1,
        priority_fields=["rango", "salida", "marca"],
    )

    print_result("CASO 2 - Sensor con rango", result_2)

    # --------------------------------------------------------
    # Caso 3: máximo de preguntas alcanzado
    # --------------------------------------------------------
    context_3 = {
        "familia": "sensor",
        "rango": "0-10 bar",
        "salida": None,
        "marca": None,
    }

    result_3 = decide_next_step(
        context=context_3,
        questions_asked=3,
        priority_fields=["rango", "salida", "marca"],
    )

    print_result("CASO 3 - Máximo de preguntas", result_3)

    # --------------------------------------------------------
    # Caso 4: knowledge simulado desde catálogo
    # --------------------------------------------------------
    catalog_knowledge = {
        "categoria": "sensor",
        "signal_attributes": {
            "rango": ["0-10 bar"],
            "salida": ["4-20 mA"],
            "conexion": ["1/4 NPT"],
        },
        "priority_fields": ["rango", "salida", "conexion", "marca"],
    }

    context_4 = {
        "familia": "sensor",
        "rango": "0-10 bar",
        "salida": None,
        "conexion": None,
        "marca": None,
    }

    result_4 = decide_with_catalog_knowledge(
        context=context_4,
        catalog_knowledge=catalog_knowledge,
        questions_asked=1,
    )

    print_result("CASO 4 - Decisión con knowledge de catálogo", result_4)


if __name__ == "__main__":
    run_tests()