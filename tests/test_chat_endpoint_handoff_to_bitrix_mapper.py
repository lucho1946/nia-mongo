# ============================================================
# tests/test_chat_endpoint_handoff_to_bitrix_mapper.py
# ============================================================
# OBJETIVO:
# Validar el puente completo previo a Bitrix:
#
# /chat endpoint real
# → commercial_handoff público
# → Bitrix mapper preview
# → payload preparado para tasks.task.add
#
# Importante:
# - Este test NO llama Bitrix.
# - No requiere webhook.
# - No crea tareas reales.
# - Solo valida que el handoff generado por NIA es compatible
#   con el mapper preparado para Bitrix.
# ============================================================

import json
import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

from main import app  # noqa: E402
from integrations.bitrix_mapper import (  # noqa: E402
    map_opportunity_to_bitrix_preview,
    map_opportunity_to_bitrix_task_payload,
)


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


def create_web_handoff_from_chat() -> dict:
    """
    Ejecuta conversación web de dos turnos para obtener commercial_handoff.
    """
    r1 = client.post(
        "/chat",
        json={
            "mensaje": "busco el 300203",
            "canal": "web",
            "cliente_id": "test_endpoint_bitrix_mapper_web_001",
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
            "cliente_id": "test_endpoint_bitrix_mapper_web_001",
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
        "Debe existir commercial_handoff como dict.",
    )

    return handoff


def run_case_handoff_maps_to_bitrix_preview_without_responsible():
    print_section("CASO 1: handoff mapea a preview Bitrix sin responsible_id")

    handoff = create_web_handoff_from_chat()

    preview = map_opportunity_to_bitrix_preview(handoff)

    show_json("BITRIX PREVIEW WITHOUT RESPONSIBLE", preview)

    assert_condition(
        preview.get("ok") is True,
        "Preview debe generarse correctamente.",
    )

    assert_condition(
        preview.get("ready_to_send") is False,
        "Sin responsible_id no debe estar listo para enviar.",
    )

    assert_condition(
        "responsible_id" in preview.get("missing", []),
        "Debe indicar responsible_id como faltante.",
    )

    assert_condition(
        preview.get("target") == "bitrix",
        "El target debe ser bitrix.",
    )

    assert_condition(
        preview.get("method") == "tasks.task.add",
        "El método debe ser tasks.task.add.",
    )

    assert_condition(
        "Nueva cotización NIA" in preview.get("title", ""),
        "El título debe indicar nueva cotización NIA.",
    )

    assert_condition(
        "300203" in preview.get("title", ""),
        "El título debe incluir el código del producto.",
    )

    assert_condition(
        "Luis Diaz" in preview.get("title", ""),
        "El título debe incluir el cliente.",
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

    assert_condition(
        "Código: 300203" in description,
        "La descripción debe incluir código de producto.",
    )

    assert_condition(
        "Precio: $480,393 COP" in description,
        "La descripción debe incluir precio.",
    )


def run_case_handoff_maps_to_bitrix_payload_with_responsible():
    print_section("CASO 2: handoff mapea a payload Bitrix con responsible_id")

    handoff = create_web_handoff_from_chat()

    payload = map_opportunity_to_bitrix_task_payload(
        handoff,
        responsible_id=123,
    )

    show_json("BITRIX PAYLOAD WITH RESPONSIBLE", payload)

    assert_condition(
        payload.get("ok") is True,
        "Payload debe generarse correctamente.",
    )

    assert_condition(
        payload.get("ready_to_send") is True,
        "Con responsible_id debe estar listo para enviar.",
    )

    assert_condition(
        payload.get("missing") == [],
        "No debe tener faltantes si responsible_id está presente.",
    )

    assert_condition(
        payload.get("method") == "tasks.task.add",
        "El método debe ser tasks.task.add.",
    )

    fields = payload.get("fields") or {}

    assert_condition(
        fields.get("RESPONSIBLE_ID") == 123,
        "Debe incluir RESPONSIBLE_ID.",
    )

    assert_condition(
        fields.get("PRIORITY") == 1,
        "Debe conservar prioridad normal.",
    )

    assert_condition(
        "NIA" in fields.get("TAGS", []),
        "Debe incluir tag NIA.",
    )

    assert_condition(
        "oportunidad_comercial" in fields.get("TAGS", []),
        "Debe incluir tag oportunidad_comercial.",
    )

    source = payload.get("source") or {}

    assert_condition(
        source.get("opportunity_id"),
        "Debe conservar opportunity_id en source.",
    )

    assert_condition(
        source.get("session_id"),
        "Debe conservar session_id en source.",
    )


def main():
    print("=" * 70)
    print("NIA CHAT ENDPOINT HANDOFF TO BITRIX MAPPER TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_handoff_maps_to_bitrix_preview_without_responsible()
    run_case_handoff_maps_to_bitrix_payload_with_responsible()

    print("\nFIN TEST CHAT ENDPOINT HANDOFF TO BITRIX MAPPER ✅")


if __name__ == "__main__":
    main()