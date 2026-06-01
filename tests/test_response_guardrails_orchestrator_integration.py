# ============================================================
# tests/test_response_guardrails_orchestrator_integration.py
# ============================================================
# OBJETIVO:
# Validar que response_guardrails ya está conectado al orquestador
# en modo metadata.
#
# Este test NO espera bloqueo ni reescritura de respuestas.
# Solo valida que cada respuesta real del orquestador tenga
# response_guardrails con diagnóstico seguro.
# ============================================================

from pathlib import Path
import os
import json

from orchestration.nia_orchestrator import process_message
from memory.conversation_memory import clear_session


def load_local_env():
    env_path = Path(__file__).resolve().parents[1] / ".env"

    if not env_path.exists():
        print("NO EXISTE .env EN:", env_path)
        return

    with env_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


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


def assert_guardrails_present(response: dict, label: str):
    guardrails = response.get("response_guardrails")

    assert_condition(
        isinstance(guardrails, dict),
        f"{label}: debe incluir response_guardrails.",
    )

    assert_condition(
        guardrails.get("version") == "response_guardrails_v1",
        f"{label}: debe usar response_guardrails_v1.",
    )

    assert_condition(
        guardrails.get("source") == "nia_orchestrator",
        f"{label}: source debe ser nia_orchestrator.",
    )

    assert_condition(
        guardrails.get("recommendation") in ["allow", "review"],
        f"{label}: recommendation debe ser allow o review.",
    )

    assert_condition(
        guardrails.get("risk_level") in ["none", "low", "medium", "high"],
        f"{label}: risk_level inválido.",
    )


def run_case_greeting_has_response_guardrails():
    print_section("CASO 1: saludo trae response_guardrails")

    response = process_message(
        "hola",
        canal="web",
        cliente_id="test_response_guardrails_integration_001",
    )

    show_json("RESPUESTA SALUDO", response)

    assert_guardrails_present(response, "saludo")

    assert_condition(
        response["response_guardrails"].get("recommendation") == "allow",
        "Saludo debe permitirse.",
    )

    clear_session(response.get("session_id"))


def run_case_product_code_has_response_guardrails():
    print_section("CASO 2: producto por código trae response_guardrails")

    response = process_message(
        "busco el 300203",
        canal="web",
        cliente_id="test_response_guardrails_integration_002",
    )

    show_json("RESPUESTA PRODUCTO", response)

    assert_guardrails_present(response, "producto")

    assert_condition(
        response["response_guardrails"].get("recommendation") == "allow",
        "Producto con card fuente debe permitirse.",
    )

    assert_condition(
        response["response_guardrails"].get("product_count", 0) >= 1,
        "Producto por código debe tener product_count >= 1.",
    )

    clear_session(response.get("session_id"))


def run_case_internal_query_has_response_guardrails():
    print_section("CASO 3: consulta interna trae response_guardrails")

    response = process_message(
        "¿Qué conocimiento tienes conectado?",
        canal="web",
        cliente_id="test_response_guardrails_integration_003",
    )

    show_json("RESPUESTA CONSULTA INTERNA", response)

    assert_guardrails_present(response, "consulta interna")

    assert_condition(
        response.get("decision_reason") == "public_safe_internal_nia_query",
        "Debe responder por guardrail público interno.",
    )

    assert_condition(
        response["response_guardrails"].get("recommendation") == "allow",
        "Respuesta pública segura debe permitirse.",
    )

    clear_session(response.get("session_id"))


def main():
    print("=" * 70)
    print("NIA RESPONSE GUARDRAILS ORCHESTRATOR INTEGRATION TEST")
    print("=" * 70)

    load_local_env()

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_greeting_has_response_guardrails()
    run_case_product_code_has_response_guardrails()
    run_case_internal_query_has_response_guardrails()

    print("\nFIN TEST RESPONSE GUARDRAILS ORCHESTRATOR INTEGRATION ✅")


if __name__ == "__main__":
    main()