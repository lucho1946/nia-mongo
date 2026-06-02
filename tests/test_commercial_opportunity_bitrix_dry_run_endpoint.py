# ============================================================
# tests/test_commercial_opportunity_bitrix_dry_run_endpoint.py
# ============================================================
# OBJETIVO:
# Validar que una oportunidad comercial guardada pueda pasar por
# el cliente Bitrix en modo dry-run, sin enviar nada a Bitrix.
#
# Flujo:
# /chat
# → commercial_handoff
# → opportunity_saved
# → /commercial-opportunities/{id}/bitrix-dry-run
# → create_bitrix_task_from_opportunity(dry_run=True)
# → sent=false
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


def clear_bitrix_env():
    """
    Limpia variables Bitrix para que el test sea seguro y controlado.
    """
    for key in [
        "BITRIX_ENABLED",
        "BITRIX_WEBHOOK_URL",
        "BITRIX_RESPONSIBLE_ID",
    ]:
        os.environ.pop(key, None)


def create_saved_opportunity_from_chat() -> dict:
    """
    Crea una oportunidad real desde /chat y retorna commercial_handoff.
    """
    r1 = client.post(
        "/chat",
        json={
            "mensaje": "busco el 300203",
            "canal": "web",
            "cliente_id": "test_bitrix_dry_run_endpoint_001",
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
            "cliente_id": "test_bitrix_dry_run_endpoint_001",
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


def run_case_bitrix_dry_run_from_saved_opportunity_default_disabled():
    print_section("CASO 1: dry-run Bitrix con configuración por defecto deshabilitada")

    clear_bitrix_env()

    handoff = create_saved_opportunity_from_chat()
    opportunity_id = handoff.get("opportunity_id")

    response = client.post(
        f"/commercial-opportunities/{opportunity_id}/bitrix-dry-run"
    )

    assert_condition(
        response.status_code == 200,
        f"Dry-run debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("BITRIX DRY RUN ENDPOINT RESPONSE", payload)

    assert_condition(
        payload.get("ok") is True,
        "El endpoint debe responder ok true.",
    )

    assert_condition(
        payload.get("sent") is False,
        "El endpoint no debe enviar nada a Bitrix.",
    )

    assert_condition(
        payload.get("mode") == "dry_run",
        "Debe estar en modo dry_run.",
    )

    bitrix_result = payload.get("bitrix_result") or {}

    assert_condition(
        bitrix_result.get("sent") is False,
        "El cliente Bitrix no debe enviar.",
    )

    assert_condition(
        bitrix_result.get("bitrix_enabled") is False,
        "Bitrix debe estar deshabilitado por defecto.",
    )

    assert_condition(
        "bitrix_disabled" in bitrix_result.get("blocked_reasons", []),
        "Debe bloquear por bitrix_disabled.",
    )

    assert_condition(
        "dry_run_enabled" in bitrix_result.get("blocked_reasons", []),
        "Debe bloquear por dry_run_enabled.",
    )

    payload_mapper = bitrix_result.get("payload") or {}

    assert_condition(
        payload_mapper.get("target") == "bitrix",
        "El payload debe apuntar a Bitrix.",
    )

    assert_condition(
        payload_mapper.get("method") == "tasks.task.add",
        "El payload debe usar tasks.task.add.",
    )


def run_case_bitrix_dry_run_ready_but_not_sent():
    print_section("CASO 2: dry-run con configuración completa no envía")

    clear_bitrix_env()

    os.environ["BITRIX_ENABLED"] = "true"
    os.environ["BITRIX_WEBHOOK_URL"] = "https://example.bitrix24.com/rest/fake/"
    os.environ["BITRIX_RESPONSIBLE_ID"] = "123"

    handoff = create_saved_opportunity_from_chat()
    opportunity_id = handoff.get("opportunity_id")

    response = client.post(
        f"/commercial-opportunities/{opportunity_id}/bitrix-dry-run"
    )

    assert_condition(
        response.status_code == 200,
        f"Dry-run listo debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("BITRIX DRY RUN READY RESPONSE", payload)

    assert_condition(
        payload.get("sent") is False,
        "Aunque esté listo, dry-run no debe enviar.",
    )

    bitrix_result = payload.get("bitrix_result") or {}

    assert_condition(
        bitrix_result.get("ready_to_send") is True,
        "Con configuración completa debe estar listo técnicamente.",
    )

    assert_condition(
        bitrix_result.get("sent") is False,
        "No debe enviar en dry-run.",
    )

    assert_condition(
        bitrix_result.get("mode") == "dry_run",
        "Debe quedar en modo dry_run.",
    )

    assert_condition(
        "dry_run_enabled" in bitrix_result.get("blocked_reasons", []),
        "Debe bloquear por dry_run_enabled.",
    )

    payload_mapper = bitrix_result.get("payload") or {}
    fields = payload_mapper.get("fields") or {}

    assert_condition(
        payload_mapper.get("ready_to_send") is True,
        "El payload debe quedar listo para envío futuro.",
    )

    assert_condition(
        fields.get("RESPONSIBLE_ID") == 123,
        "Debe incluir RESPONSIBLE_ID en payload.",
    )


def run_case_bitrix_dry_run_not_found():
    print_section("CASO 3: dry-run Bitrix de oportunidad inexistente")

    clear_bitrix_env()

    response = client.post(
        "/commercial-opportunities/cotizacion_no_existe_123/bitrix-dry-run"
    )

    show_json("BITRIX DRY RUN NOT FOUND RESPONSE", {
        "status_code": response.status_code,
        "body": response.json() if response.text else None,
    })

    assert_condition(
        response.status_code == 404,
        "Debe responder 404 si la oportunidad no existe.",
    )


def main():
    print("=" * 70)
    print("NIA COMMERCIAL OPPORTUNITY BITRIX DRY RUN ENDPOINT TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_bitrix_dry_run_from_saved_opportunity_default_disabled()
    run_case_bitrix_dry_run_ready_but_not_sent()
    run_case_bitrix_dry_run_not_found()

    print("\nFIN TEST COMMERCIAL OPPORTUNITY BITRIX DRY RUN ENDPOINT ✅")


if __name__ == "__main__":
    main()