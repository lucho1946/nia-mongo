# ============================================================
# tests/test_chat_endpoint_commercial_handoff.py
# ============================================================
# OBJETIVO:
# Validar que el endpoint real POST /chat expone correctamente
# commercial_handoff cuando una conversación llega a cotización.
#
# Este test pasa por:
# FastAPI TestClient
# → main.app
# → routers/chat.py
# → process_chat_request()
# → nia_orchestrator
# → commercial_handoff
# → ChatResponse público
#
# Importante:
# - No expone metadata interna de NIA OS.
# - Sí expone commercial_handoff, porque es contrato público
#   permitido para integración futura con asesor, CRM o Bitrix.
# ============================================================

import json
import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient

# Cargar .env antes de importar main/app.
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


def assert_no_internal_metadata(payload: dict):
    """
    Verifica que el endpoint público no filtre metadata interna.
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


def run_case_endpoint_web_handoff_after_customer_data():
    print_section("CASO 1: endpoint /chat genera handoff web en segundo turno")

    # --------------------------------------------------------
    # Turno 1: cliente pide producto exacto.
    # --------------------------------------------------------
    r1 = client.post(
        "/chat",
        json={
            "mensaje": "busco el 300203",
            "canal": "web",
            "cliente_id": "test_endpoint_handoff_web_001",
        },
    )

    assert_condition(
        r1.status_code == 200,
        f"Turno 1 debe responder 200. Status: {r1.status_code}, body: {r1.text}",
    )

    p1 = r1.json()

    show_json("RESPUESTA WEB TURNO 1", p1)

    assert_no_internal_metadata(p1)

    assert_condition(
        p1.get("session_id"),
        "Turno 1 debe devolver session_id.",
    )

    assert_condition(
        len(p1.get("productos", [])) >= 1,
        "Turno 1 debe devolver al menos un producto.",
    )

    assert_condition(
        p1.get("commercial_handoff") is None,
        "Turno 1 todavía no debe tener handoff si faltan datos del cliente.",
    )

    session_id = p1.get("session_id")

    # --------------------------------------------------------
    # Turno 2: cliente entrega datos mínimos para cotización.
    # --------------------------------------------------------
    r2 = client.post(
        "/chat",
        json={
            "mensaje": "Luis Diaz, Viaindustrial, luis2004diazalzate@gmail.com",
            "session_id": session_id,
            "canal": "web",
            "cliente_id": "test_endpoint_handoff_web_001",
        },
    )

    assert_condition(
        r2.status_code == 200,
        f"Turno 2 debe responder 200. Status: {r2.status_code}, body: {r2.text}",
    )

    p2 = r2.json()

    show_json("RESPUESTA WEB TURNO 2", p2)

    assert_no_internal_metadata(p2)

    handoff = p2.get("commercial_handoff")

    assert_condition(
        isinstance(handoff, dict),
        "Turno 2 debe exponer commercial_handoff como dict.",
    )

    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "El handoff debe ser de tipo cotizacion.",
    )

    assert_condition(
        handoff.get("estado") == "lista_para_asesor",
        "El handoff debe quedar listo para asesor.",
    )

    assert_condition(
        handoff.get("opportunity_saved") is True,
        "La oportunidad debe quedar guardada.",
    )

    assert_condition(
        handoff.get("producto_codigo") == "300203",
        "El handoff debe conservar el código del producto.",
    )

    assert_condition(
        handoff.get("cliente") == "Luis Diaz",
        "El handoff debe conservar el nombre del cliente.",
    )

    assert_condition(
        handoff.get("empresa") == "Viaindustrial",
        "El handoff debe conservar la empresa.",
    )

    assert_condition(
        handoff.get("correo") == "luis2004diazalzate@gmail.com",
        "El handoff debe conservar el correo.",
    )


def run_case_endpoint_whatsapp_handoff_with_channel_phone():
    print_section("CASO 2: endpoint /chat genera handoff WhatsApp con teléfono del canal")

    response = client.post(
        "/chat",
        json={
            "mensaje": "busco el 300203",
            "canal": "whatsapp",
            "cliente_id": "573001234567",
        },
    )

    assert_condition(
        response.status_code == 200,
        f"WhatsApp debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("RESPUESTA WHATSAPP", payload)

    assert_no_internal_metadata(payload)

    handoff = payload.get("commercial_handoff")

    assert_condition(
        isinstance(handoff, dict),
        "WhatsApp debe exponer commercial_handoff como dict.",
    )

    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "El handoff WhatsApp debe ser de tipo cotizacion.",
    )

    assert_condition(
        handoff.get("opportunity_saved") is True,
        "La oportunidad WhatsApp debe quedar guardada.",
    )

    assert_condition(
        handoff.get("telefono") == "3001234567",
        "Debe tomar el teléfono desde el canal WhatsApp.",
    )

    assert_condition(
        handoff.get("contact_source") == "channel_phone",
        "Debe indicar que el contacto salió del teléfono del canal.",
    )

    assert_condition(
        handoff.get("producto_codigo") == "300203",
        "Debe conservar el código del producto.",
    )


def main():
    print("=" * 70)
    print("NIA CHAT ENDPOINT COMMERCIAL HANDOFF TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_endpoint_web_handoff_after_customer_data()
    run_case_endpoint_whatsapp_handoff_with_channel_phone()

    print("\nFIN TEST CHAT ENDPOINT COMMERCIAL HANDOFF ✅")


if __name__ == "__main__":
    main()