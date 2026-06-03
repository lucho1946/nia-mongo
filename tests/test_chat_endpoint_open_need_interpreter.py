# ============================================================
# tests/test_chat_endpoint_open_need_interpreter.py
# ============================================================
# OBJETIVO:
# Validar que /chat pueda atender una necesidad abierta usando
# el intérprete OpenAI/fallback, sin llamar OpenAI real.
#
# Caso:
# "medir velocidad de aire en ductos"
# → query segura: anemómetro medidor velocidad aire ductos ventilación
# → búsqueda en catálogo real
# → respuesta con productos reales
# ============================================================

import json
import os

from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

# Forzamos OpenAI apagado para que el test no consuma tokens.
os.environ["OPENAI_ENABLED"] = "false"
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")

from main import app  # noqa: E402


client = TestClient(app)


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


def assert_public_metadata_contract(payload: dict):
    """
    Valida el contrato público actualizado de /chat.

    Por decisión de integración, /chat ahora SÍ expone:
    - decision_reason
    - nia_os
    - context

    Pero NO debe exponer campos internos sueltos en la raíz.
    """

    # Estos campos ahora hacen parte del contrato público controlado.
    assert_condition(
        "decision_reason" in payload,
        "El contrato público debe incluir decision_reason.",
    )

    assert_condition(
        "nia_os" in payload,
        "El contrato público debe incluir nia_os.",
    )

    assert_condition(
        "context" in payload,
        "El contrato público debe incluir context.",
    )

    assert_condition(
        payload.get("nia_os") is None or isinstance(payload.get("nia_os"), dict),
        "nia_os debe ser dict o null.",
    )

    assert_condition(
        payload.get("context") is None or isinstance(payload.get("context"), dict),
        "context debe ser dict o null.",
    )

    # Estos campos NO deben salir como campos raíz.
    # Si existen dentro de nia_os como runtime_policy/runtime_policy_check,
    # está permitido porque van agrupados bajo metadata controlada.
    forbidden_root_fields = {
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
        "semantic_profile",
    }

    leaked = forbidden_root_fields.intersection(set(payload.keys()))

    assert_condition(
        not leaked,
        f"No debe exponer metadata interna suelta en raíz. Campos filtrados: {sorted(leaked)}",
    )


def run_case_open_need_air_speed():
    print_section("CASO 1: necesidad abierta de velocidad de aire")

    response = client.post(
        "/chat",
        json={
            "mensaje": "Hola, estoy buscando un equipo para medir la velocidad del aire en unos ductos de ventilación.",
            "canal": "web",
            "cliente_id": "test_open_need_air_speed_001",
        },
    )

    assert_condition(
        response.status_code == 200,
        f"/chat debe responder 200. Status: {response.status_code}, body: {response.text}",
    )

    payload = response.json()

    show_json("OPEN NEED CHAT RESPONSE", payload)
    
    assert_condition(
        payload.get("decision_reason") == "openai_interpreted_open_need",
        "Debe marcar decision_reason=openai_interpreted_open_need.",
    )

    nia_os = payload.get("nia_os") or {}

    assert_condition(
        isinstance(nia_os, dict),
        "nia_os debe venir como dict.",
    )

    assert_condition(
        nia_os.get("intent") in ["consulta_producto_descripcion", "producto"],
        "nia_os.intent debe reflejar consulta de producto por descripción.",
    )

    assert_public_metadata_contract(payload)

    assert_condition(
        payload.get("respuesta"),
        "Debe devolver respuesta pública.",
    )

    productos = payload.get("productos", [])

    assert_condition(
        isinstance(productos, list),
        "productos debe ser una lista.",
    )

    assert_condition(
        len(productos) >= 1,
        "Debe devolver al menos un producto desde catálogo real.",
    )

    serialized = json.dumps(payload, ensure_ascii=False).lower()

    assert_condition(
        "anem" in serialized or "aire" in serialized or "velocidad" in serialized,
        "La respuesta debe estar relacionada con medición de aire/anemómetro.",
    )


def main():
    print("=" * 70)
    print("NIA CHAT ENDPOINT OPEN NEED INTERPRETER TEST")
    print("=" * 70)

    print("OPENAI_ENABLED:", os.getenv("OPENAI_ENABLED"))
    print("OPENAI_MODEL:", os.getenv("OPENAI_MODEL"))
    print("OPENAI_API_KEY:", bool(os.getenv("OPENAI_API_KEY")))
    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_open_need_air_speed()

    print("\nFIN TEST CHAT ENDPOINT OPEN NEED INTERPRETER ✅")


if __name__ == "__main__":
    main()