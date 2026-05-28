# ============================================================
# test_commercial_quote_followup.py
# ============================================================
# Prueba de seguimiento posterior a cotización enviada/recibida.
# ============================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from orchestration.nia_orchestrator import process_message
from memory.conversation_memory import get_session, clear_session


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"

    if not env_path.exists():
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


def assert_condition(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def response_text(response: Dict[str, Any]) -> str:
    return response.get("response") or response.get("respuesta") or ""


def print_response(title: str, response: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print("session_id:", response.get("session_id"))
    print("estado:", response.get("estado") or response.get("estado_negociacion"))
    print("respuesta:")
    print(response_text(response))


def prepare_completed_quote_flow() -> str:
    """
    Crea una conversación con:
    producto activo + cotización iniciada + datos comerciales completos.
    """
    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    process_message("quiero cotizar este producto", session_id=session_id)
    process_message("Luisa", session_id=session_id)
    process_message("Industrias ABC", session_id=session_id)
    process_message("luisa@industriasabc.com", session_id=session_id)

    return session_id


def test_quote_sent_followup() -> None:
    print("\n" + "#" * 70)
    print("CASO 1: Ya me enviaron la cotización")
    print("#" * 70)

    session_id = prepare_completed_quote_flow()

    response = process_message(
        "Ya me enviaron la cotización",
        session_id=session_id,
    )

    session = get_session(session_id) or {}
    text = response_text(response)

    print_response("RESPUESTA SEGUIMIENTO", response)
    print("estado_negociacion:", session.get("estado_negociacion"))
    print("commercial_process_state:", session.get("commercial_process_state"))
    print("siguiente_paso:", session.get("siguiente_paso"))

    assert_condition(
        "continuamos sobre la cotización enviada" in text,
        "Debe responder seguimiento sobre cotización enviada.",
    )

    assert_condition(
        "iniciar la cotización" not in text,
        "No debe iniciar una cotización nueva.",
    )

    assert_condition(
        "nombre, empresa" not in text.lower(),
        "No debe volver a pedir datos comerciales completos.",
    )

    assert_condition(
        session.get("estado_negociacion") == "seguimiento_cotizacion",
        "Debe quedar estado_negociacion = seguimiento_cotizacion.",
    )

    assert_condition(
        session.get("commercial_process_state") == "seguimiento",
        "Debe mapear al estado seguimiento del Commercial Spine.",
    )

    clear_session(session_id)


def test_quote_received_followup() -> None:
    print("\n" + "#" * 70)
    print("CASO 2: Ya recibí la cotización")
    print("#" * 70)

    session_id = prepare_completed_quote_flow()

    response = process_message(
        "Ya recibí la cotización",
        session_id=session_id,
    )

    text = response_text(response)

    print_response("RESPUESTA RECIBÍ COTIZACIÓN", response)

    assert_condition(
        "continuamos sobre la cotización enviada" in text,
        "Debe manejar cotización recibida como seguimiento.",
    )

    assert_condition(
        "iniciar la cotización" not in text,
        "No debe reiniciar cotización.",
    )

    clear_session(session_id)


def test_quote_reviewed_followup() -> None:
    print("\n" + "#" * 70)
    print("CASO 3: Ya la revisé")
    print("#" * 70)

    session_id = prepare_completed_quote_flow()

    response = process_message(
        "Ya la revisé",
        session_id=session_id,
    )

    text = response_text(response)

    print_response("RESPUESTA YA LA REVISÉ", response)

    assert_condition(
        "continuamos sobre la cotización enviada" in text,
        "Debe manejar 'ya la revisé' como seguimiento.",
    )

    assert_condition(
        "detalle del producto" not in text.lower(),
        "No debe pedir detalle de producto.",
    )

    clear_session(session_id)


def test_new_quote_still_works() -> None:
    print("\n" + "#" * 70)
    print("CASO 4: Quiero cotizar sigue iniciando cotización")
    print("#" * 70)

    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    response = process_message(
        "quiero cotizar este producto",
        session_id=session_id,
    )

    text = response_text(response)

    print_response("RESPUESTA INICIO COTIZACIÓN", response)

    assert_condition(
        "iniciar la cotización" in text,
        "Debe seguir funcionando el inicio normal de cotización.",
    )

    clear_session(session_id)


def main() -> None:
    print("\n" + "=" * 70)
    print("NIA COMMERCIAL QUOTE FOLLOWUP TEST")
    print("=" * 70)

    load_local_env()

    assert_condition(
        bool(os.getenv("MONGO_CONNECTION_STRING")),
        "MONGO_CONNECTION_STRING debe estar configurado.",
    )

    test_quote_sent_followup()
    test_quote_received_followup()
    test_quote_reviewed_followup()
    test_new_quote_still_works()

    print("\nFIN TEST COMMERCIAL QUOTE FOLLOWUP ✅")


if __name__ == "__main__":
    main()