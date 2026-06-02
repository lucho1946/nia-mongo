# ============================================================
# tests/test_commercial_opportunity_bitrix_preview_endpoint.py
# ============================================================
# OBJETIVO:
# Validar que una oportunidad comercial guardada pueda consultarse
# desde el endpoint interno y transformarse en preview Bitrix
# sin enviar nada a Bitrix.
#
# Flujo:
# /chat
# → commercial_handoff
# → opportunity_saved
# → /commercial-opportunities/{id}/bitrix-preview
# → preview seguro Bitrix
# ============================================================

import json
import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

from main import app  # noqa: E402


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


def create_saved_opportunity_from_chat() -> dict:
    """
    Crea una oportunidad real desde /chat y retorna commercial_handoff.
    """
    r1 = client.post(
        "/chat",
        json={
            "mensaje": "busco el 300203",
            "canal": "web",
            "cliente_id": "test_bitrix_preview_endpoint_001",
        },
    )

    assert_condition(
        r1.status_code == 200,
        f"Turno 1 debe responder 200. Status: {r1.status_code}, body: {r1.text}",
    )

    p1 = r1.json()
    session_id = p1.get("session_id")

    assert_condition(
        session_id,
        "Turno 1 debe devolver session_id.",
    )

    r2 = client.post(
        "/chat",
        json={
            "mensaje": "Luis Diaz, Viaindustrial, luis2004diazalzate@gmail.com",
            "session_id": session_id,
            "canal": "web",
            "cliente_id": "test_bitrix_preview_endpoint_001",
        },
    )

    assert_condition(
        r2.status_code == 200,
        f"Turno 2 debe responder 200. Status: {r2.status_code}, body: {r2.text}",
    )

    p2 = r2.json()

    show_json("CHAT RESPONSE WITH HANDOFF", p2)

    handoff = p2.get("commercial_handoff")

    assert_condition(
        isinstance(handoff, dict),
        "Debe existir commercial_handoff.",
    )

    assert_condition(
        handoff.get("opportunity_saved") is True,
        "La oportunidad debe quedar guardada.",
    )

    assert_condition(
        handoff.get("opportunity_id"),
        "Debe existir opportunity_id.",
    )

    return handoff


def run_case_bitrix_preview_from_saved_opportunity():
    print_section("CASO 1: preview Bitrix desde oportunidad guardada")

    handoff = create_saved_opportunity_from_chat()
    opportunity_id = handoff.get("opportunity_id")

    response = client.get(
        f"/commercial-opportunities/{opportunity_id}/bitrix-preview"
    )

    assert_condition(
        response.status_code == 200,
        f"Preview debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("BITRIX PREVIEW ENDPOINT RESPONSE", payload)

    assert_condition(
        payload.get("ok") is True,
        "El endpoint debe responder ok true.",
    )

    assert_condition(
        payload.get("sent") is False,
        "El endpoint no debe enviar nada a Bitrix.",
    )

    assert_condition(
        payload.get("mode") == "preview",
        "Debe estar en modo preview.",
    )

    bitrix_preview = payload.get("bitrix_preview") or {}

    assert_condition(
        bitrix_preview.get("mode") == "preview",
        "El cliente Bitrix debe devolver modo preview.",
    )

    assert_condition(
        bitrix_preview.get("bitrix_enabled") is False,
        "Bitrix debe seguir deshabilitado por defecto.",
    )

    preview = bitrix_preview.get("preview") or {}

    assert_condition(
        preview.get("target") == "bitrix",
        "El preview debe apuntar a Bitrix.",
    )

    assert_condition(
        preview.get("method") == "tasks.task.add",
        "El preview debe usar método tasks.task.add.",
    )

    assert_condition(
        "Nueva cotización NIA" in preview.get("title", ""),
        "El título debe indicar nueva cotización NIA.",
    )

    assert_condition(
        "300203" in preview.get("title", ""),
        "El título debe incluir código 300203.",
    )

    description = preview.get("description", "")

    assert_condition(
        "Cliente: Luis Diaz" in description,
        "La descripción debe incluir cliente.",
    )

    assert_condition(
        "Empresa: Viaindustrial" in description,
        "La descripción debe incluir empresa.",
    )

    assert_condition(
        "Correo: luis2004diazalzate@gmail.com" in description,
        "La descripción debe incluir correo.",
    )


def run_case_bitrix_preview_not_found():
    print_section("CASO 2: preview Bitrix de oportunidad inexistente")

    response = client.get(
        "/commercial-opportunities/cotizacion_no_existe_123/bitrix-preview"
    )

    show_json("BITRIX PREVIEW NOT FOUND RESPONSE", {
        "status_code": response.status_code,
        "body": response.json() if response.text else None,
    })

    assert_condition(
        response.status_code == 404,
        "Debe responder 404 si la oportunidad no existe.",
    )


def main():
    print("=" * 70)
    print("NIA COMMERCIAL OPPORTUNITY BITRIX PREVIEW ENDPOINT TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_bitrix_preview_from_saved_opportunity()
    run_case_bitrix_preview_not_found()

    print("\nFIN TEST COMMERCIAL OPPORTUNITY BITRIX PREVIEW ENDPOINT ✅")


if __name__ == "__main__":
    main()