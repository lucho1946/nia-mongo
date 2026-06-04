# ============================================================
# tests/test_chat_endpoint_open_need_interpreter.py
# ============================================================
# OBJETIVO:
# Validar que /chat atiende de forma segura una necesidad abierta
# cuando OpenAI está apagado.
#
# Arquitectura actual:
# - OpenAI interpreta necesidades abiertas cuando está disponible.
# - Si OpenAI está apagado, el fallback conservador NO debe adivinar.
# - /chat debe pedir aclaración sin inventar productos.
# - El catálogo real solo debe usarse cuando existe intención/query segura.
# ============================================================

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient


# ============================================================
# BOOTSTRAP DE IMPORTS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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

    /chat puede exponer:
    - decision_reason
    - nia_os
    - context

    Pero no debe exponer metadata interna suelta en raíz.
    """

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


def run_case_open_need_air_speed_with_openai_disabled():
    print_section("CASO 1: necesidad abierta con OpenAI apagado usa fallback conservador")

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

    assert_public_metadata_contract(payload)

    # Con OpenAI apagado, NIA no debe fingir interpretación semántica abierta.
    assert_condition(
    payload.get("decision_reason") in [
        "missing_relevant_field",
        "need_clarification",
        "no_relevant_product_context",
        "fallback_conservative_clarification",
        "semantic_interpreter_requires_clarification",
    ],
    f"Con OpenAI apagado debe pedir aclaración, no marcar openai_interpreted_open_need. decision_reason={payload.get('decision_reason')}",
    )

    assert_condition(
        payload.get("estado") in ["recopilando", "preguntando", "pendiente"],
        f"Debe quedar en estado de recopilación/aclaración. estado={payload.get('estado')}",
    )

    respuesta = payload.get("respuesta", "")

    assert_condition(
        isinstance(respuesta, str) and respuesta.strip(),
        "Debe devolver una respuesta pública.",
    )

    assert_condition(
        "?" in respuesta or "¿" in respuesta,
        "Debe hacer una pregunta de aclaración.",
    )

    productos = payload.get("productos", [])

    assert_condition(
        isinstance(productos, list),
        "productos debe ser una lista.",
    )

    assert_condition(
        len(productos) == 0,
        "Con OpenAI apagado y necesidad abierta, no debe devolver productos inventados o inferidos.",
    )

    nia_os = payload.get("nia_os") or {}

    assert_condition(
        isinstance(nia_os, dict),
        "nia_os debe venir como dict.",
    )

    module_ids = nia_os.get("module_ids", [])

    assert_condition(
        isinstance(module_ids, list),
        "nia_os.module_ids debe ser una lista.",
    )

    assert_condition(
        "module_motor_interpretacion_semantica" in module_ids,
        "NIA OS debe activar el módulo de interpretación semántica para default/open need.",
    )

    assert_condition(
        "module_guardrails_no_inventar" in module_ids,
        "NIA OS debe mantener guardrails activos.",
    )

    context = payload.get("context") or {}

    assert_condition(
        isinstance(context, dict),
        "context debe ser dict.",
    )

    # Seguimos permitiendo que el mensaje quede como aplicación/contexto,
    # pero eso NO significa que pueda recomendar producto sin interpretación semántica.
    assert_condition(
        context.get("codigo_producto") in [None, ""],
        "No debe inventar código de producto.",
    )

    assert_condition(
        context.get("referencia") in [None, ""],
        "No debe inventar referencia.",
    )


# ============================================================
# TEST PYTEST
# ============================================================

def test_open_need_with_openai_disabled_uses_conservative_clarification():
    run_case_open_need_air_speed_with_openai_disabled()


# ============================================================
# EJECUCIÓN MANUAL
# ============================================================

def main():
    print("=" * 70)
    print("NIA CHAT ENDPOINT OPEN NEED INTERPRETER TEST")
    print("=" * 70)

    print("OPENAI_ENABLED:", os.getenv("OPENAI_ENABLED"))
    print("OPENAI_MODEL:", os.getenv("OPENAI_MODEL"))
    print("OPENAI_API_KEY:", bool(os.getenv("OPENAI_API_KEY")))
    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_open_need_air_speed_with_openai_disabled()

    print("\nFIN TEST CHAT ENDPOINT OPEN NEED INTERPRETER ✅")


if __name__ == "__main__":
    main()