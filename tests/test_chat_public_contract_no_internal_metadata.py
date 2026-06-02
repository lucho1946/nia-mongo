# ============================================================
# tests/test_chat_public_contract_no_internal_metadata.py
# ============================================================
# OBJETIVO:
# Validar que el contrato público de /chat no expone metadata
# interna de NIA OS.
#
# NIA OS puede usar internamente:
# - nia_os
# - runtime_policy
# - runtime_policy_check
# - document_policy
# - response_guardrails
# - nia_os_runtime_enforcement
#
# Pero el frontend/cliente final solo debe recibir el contrato
# público ChatResponse:
# - session_id
# - respuesta
# - estado
# - preguntas_hechas
# - productos
# - requiere_accion
# - metadata comercial permitida
# - commercial_handoff
# ============================================================

import json

from models.schemas import ChatRequest
from orchestration.chat_response_adapter import process_chat_request


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


def response_to_dict(response):
    """
    Convierte ChatResponse a dict compatible con Pydantic v1/v2.
    """
    if hasattr(response, "model_dump"):
        return response.model_dump()

    return response.dict()


def assert_no_internal_metadata(payload: dict):
    """
    Verifica que el contrato público no exponga campos internos.
    """
    forbidden_fields = {
        "nia_os",
        "runtime_policy",
        "runtime_policy_check",
        "document_policy",
        "response_guardrails",
        "nia_os_runtime_enforcement",
        "modules",
        "module_ids",
        "guardrails",
        "commercial_spine",
    }

    leaked = forbidden_fields.intersection(set(payload.keys()))

    assert_condition(
        not leaked,
        f"No debe exponer metadata interna en /chat. Campos filtrados: {sorted(leaked)}",
    )


def run_case_public_chat_greeting_contract():
    print_section("CASO 1: /chat saludo no expone metadata interna")

    request = ChatRequest(
        mensaje="Hola",
        canal="web",
        cliente_id="test_public_contract_greeting",
    )

    response = process_chat_request(request)
    payload = response_to_dict(response)

    show_json("PUBLIC CHAT RESPONSE", payload)

    assert_condition(
        payload.get("respuesta"),
        "Debe tener respuesta pública.",
    )

    assert_condition(
        payload.get("estado") in ["recopilando", "completado", "cerrado"],
        "Debe tener estado público válido.",
    )

    assert_no_internal_metadata(payload)


def run_case_public_chat_product_contract():
    print_section("CASO 2: /chat producto no expone metadata interna")

    request = ChatRequest(
        mensaje="busco el 300203",
        canal="web",
        cliente_id="test_public_contract_product",
    )

    response = process_chat_request(request)
    payload = response_to_dict(response)

    show_json("PUBLIC CHAT PRODUCT RESPONSE", payload)

    assert_condition(
        "respuesta" in payload,
        "Debe incluir respuesta pública.",
    )

    assert_condition(
        "productos" in payload,
        "Debe incluir productos como lista pública.",
    )

    assert_no_internal_metadata(payload)


def main():
    print("=" * 70)
    print("NIA CHAT PUBLIC CONTRACT NO INTERNAL METADATA TEST")
    print("=" * 70)

    run_case_public_chat_greeting_contract()
    run_case_public_chat_product_contract()

    print("\nFIN TEST CHAT PUBLIC CONTRACT NO INTERNAL METADATA ✅")


if __name__ == "__main__":
    main()