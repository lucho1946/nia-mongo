# ============================================================
# tests/test_chat_endpoint_public_contract.py
# ============================================================
# OBJETIVO:
# Validar que el endpoint real POST /chat no expone metadata
# interna de NIA OS.
#
# Este test pasa por:
# FastAPI TestClient
# → main.app
# → routers/chat.py
# → process_chat_request()
# → ChatResponse
#
# Diferencia con test_chat_public_contract_no_internal_metadata:
# - Ese test valida el adapter directamente.
# - Este valida el endpoint HTTP real.
# ============================================================

import json
import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from main import app


# ============================================================
# Cargar variables locales
# ============================================================
# Evita ruido de MONGO_CONNECTION_STRING no configurado cuando
# existe .env en local.
# ============================================================
load_dotenv()


client = TestClient(app)


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


def assert_no_internal_metadata(payload: dict):
    """
    Verifica que el endpoint público /chat no filtre metadata interna.
    """
    forbidden_fields = {
    "runtime_policy",
    "runtime_policy_check",
    "document_policy",
    "response_guardrails",
    "nia_os_runtime_enforcement",
    "modules",
    "module_ids",
    "guardrails",
    "commercial_spine",
    "openai_intent_interpreter",
    }

    leaked = forbidden_fields.intersection(set(payload.keys()))

    assert_condition(
        not leaked,
        f"No debe exponer metadata interna en /chat. Campos filtrados: {sorted(leaked)}",
    )
    assert_condition(
    payload.get("nia_os") is None or isinstance(payload.get("nia_os"), dict),
    "nia_os debe ser dict o null.",
    )

    assert_condition(
    payload.get("context") is None or isinstance(payload.get("context"), dict),
    "context debe ser dict o null.",
    )


def run_case_endpoint_chat_greeting():
    print_section("CASO 1: endpoint /chat saludo")

    response = client.post(
        "/chat",
        json={
            "mensaje": "Hola",
            "canal": "web",
            "cliente_id": "test_endpoint_public_contract_greeting",
        },
    )

    assert_condition(
        response.status_code == 200,
        f"/chat saludo debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("ENDPOINT CHAT GREETING RESPONSE", payload)

    assert_condition(
        payload.get("respuesta"),
        "Debe incluir respuesta pública.",
    )

    assert_condition(
        payload.get("estado") in ["recopilando", "completado", "cerrado"],
        "Debe incluir estado público válido.",
    )

    assert_condition(
        "productos" in payload,
        "Debe incluir productos como lista pública.",
    )

    assert_no_internal_metadata(payload)


def run_case_endpoint_chat_product_code():
    print_section("CASO 2: endpoint /chat producto por código")

    response = client.post(
        "/chat",
        json={
            "mensaje": "busco el 300203",
            "canal": "web",
            "cliente_id": "test_endpoint_public_contract_product",
        },
    )

    assert_condition(
        response.status_code == 200,
        f"/chat producto debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("ENDPOINT CHAT PRODUCT RESPONSE", payload)

    assert_condition(
        payload.get("respuesta"),
        "Debe incluir respuesta pública.",
    )

    assert_condition(
        "productos" in payload,
        "Debe incluir productos como lista pública.",
    )

    assert_no_internal_metadata(payload)


def main():
    print("=" * 70)
    print("NIA CHAT ENDPOINT PUBLIC CONTRACT TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_endpoint_chat_greeting()
    run_case_endpoint_chat_product_code()

    print("\nFIN TEST CHAT ENDPOINT PUBLIC CONTRACT ✅")


if __name__ == "__main__":
    main()