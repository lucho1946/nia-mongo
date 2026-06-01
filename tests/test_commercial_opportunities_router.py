# ============================================================
# tests/test_commercial_opportunities_router.py
# ============================================================
# OBJETIVO:
# Validar los endpoints internos de oportunidades comerciales.
#
# Flujo:
# 1. NIA genera una oportunidad desde /chat.
# 2. Consultamos la oportunidad por opportunity_id.
# 3. Consultamos oportunidades por session_id.
#
# Esto valida la base futura para Bitrix/CRM/panel comercial.
# ============================================================

from pathlib import Path
import os
import json

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def load_local_env():
    """
    Carga variables desde .env para pruebas locales.
    """
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


def run_case_query_opportunity_endpoints():
    print_section("CASO 1: endpoints consultan oportunidad comercial")

    # --------------------------------------------------------
    # 1. Crear flujo comercial desde /chat
    # --------------------------------------------------------
    r1 = client.post("/chat", json={
        "mensaje": "busco el 300203",
        "canal": "web",
        "cliente_id": "test_opportunity_router_001",
    })

    assert_condition(
        r1.status_code == 200,
        f"R1 debe responder 200. Status={r1.status_code} Body={r1.text}",
    )

    r1_data = r1.json()
    session_id = r1_data.get("session_id")

    assert_condition(
        session_id,
        "R1 debe devolver session_id.",
    )

    r2 = client.post("/chat", json={
        "mensaje": "Luis Diaz, ViaIndustrial, luis2004diazalzate@gmail.com",
        "session_id": session_id,
        "canal": "web",
        "cliente_id": "test_opportunity_router_001",
    })

    assert_condition(
        r2.status_code == 200,
        f"R2 debe responder 200. Status={r2.status_code} Body={r2.text}",
    )

    r2_data = r2.json()
    show_json("R2 CHAT RESPONSE", r2_data)

    handoff = r2_data.get("commercial_handoff") or {}

    assert_condition(
        handoff,
        "R2 debe devolver commercial_handoff.",
    )

    opportunity_id = handoff.get("opportunity_id")

    assert_condition(
        opportunity_id,
        "commercial_handoff debe tener opportunity_id.",
    )

    assert_condition(
        handoff.get("opportunity_saved") is True,
        "commercial_handoff debe tener opportunity_saved=True.",
    )

    # --------------------------------------------------------
    # 2. Consultar por opportunity_id
    # --------------------------------------------------------
    by_id_response = client.get(
        f"/commercial-opportunities/{opportunity_id}"
    )

    assert_condition(
        by_id_response.status_code == 200,
        (
            "Consulta por opportunity_id debe responder 200. "
            f"Status={by_id_response.status_code} Body={by_id_response.text}"
        ),
    )

    by_id_data = by_id_response.json()
    show_json("OPPORTUNITY BY ID", by_id_data)

    assert_condition(
        by_id_data.get("ok") is True,
        "Consulta por ID debe devolver ok=True.",
    )

    opportunity = by_id_data.get("opportunity") or {}

    assert_condition(
        opportunity.get("opportunity_id") == opportunity_id,
        "Debe devolver la oportunidad correcta.",
    )

    assert_condition(
        opportunity.get("producto_codigo") == "300203",
        "La oportunidad debe conservar producto 300203.",
    )

    assert_condition(
        opportunity.get("cliente") == "Luis Diaz",
        "La oportunidad debe conservar cliente.",
    )

    assert_condition(
        opportunity.get("empresa") == "Viaindustrial",
        "La oportunidad debe conservar empresa.",
    )

    assert_condition(
        opportunity.get("correo") == "luis2004diazalzate@gmail.com",
        "La oportunidad debe conservar correo.",
    )

    # --------------------------------------------------------
    # 3. Consultar por session_id
    # --------------------------------------------------------
    by_session_response = client.get(
        f"/commercial-opportunities/session/{session_id}"
    )

    assert_condition(
        by_session_response.status_code == 200,
        (
            "Consulta por session_id debe responder 200. "
            f"Status={by_session_response.status_code} Body={by_session_response.text}"
        ),
    )

    by_session_data = by_session_response.json()
    show_json("OPPORTUNITIES BY SESSION", by_session_data)

    assert_condition(
        by_session_data.get("ok") is True,
        "Consulta por sesión debe devolver ok=True.",
    )

    items = by_session_data.get("items") or []

    assert_condition(
        by_session_data.get("total", 0) >= 1,
        "Consulta por sesión debe devolver al menos una oportunidad.",
    )

    assert_condition(
        any(item.get("opportunity_id") == opportunity_id for item in items),
        "La lista por sesión debe contener la oportunidad creada.",
    )


def run_case_not_found():
    print_section("CASO 2: oportunidad inexistente responde 404")

    response = client.get(
        "/commercial-opportunities/cotizacion_no_existe_123456"
    )

    show_json("NOT FOUND RESPONSE", {
        "status_code": response.status_code,
        "body": response.json() if response.text else None,
    })

    assert_condition(
        response.status_code == 404,
        "Una oportunidad inexistente debe responder 404.",
    )


def main():
    print("=" * 70)
    print("NIA COMMERCIAL OPPORTUNITIES ROUTER TEST")
    print("=" * 70)

    load_local_env()

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_query_opportunity_endpoints()
    run_case_not_found()

    print("\nFIN TEST COMMERCIAL OPPORTUNITIES ROUTER ✅")


if __name__ == "__main__":
    main()