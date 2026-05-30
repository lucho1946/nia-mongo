# ============================================================
# test_mongo_session_store.py
# ============================================================
# Prueba de persistencia de sesiones NIA en MongoDB.
#
# Objetivo:
# - Crear sesiÃ³n.
# - Guardarla en RAM y Mongo.
# - Limpiar RAM para simular otro worker de Azure.
# - Recuperar la sesiÃ³n desde MongoDB.
# - Validar que el contexto y producto activo sobreviven.
# ============================================================

from __future__ import annotations

import json
from dotenv import load_dotenv

load_dotenv()

from memory.conversation_memory import (
    create_session,
    save_session,
    get_session,
    update_context,
    clear_session,
    _SESSIONS,
)
from memory.mongo_session_store import session_store_health


def assert_condition(condition: bool, message: str) -> None:
    """
    Assertion simple con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def main() -> None:
    print("\n" + "=" * 70)
    print("NIA MONGO SESSION STORE TEST")
    print("=" * 70)

    health = session_store_health()

    print("\nHEALTH:")
    print(json.dumps(health, ensure_ascii=False, indent=2, default=str))

    assert_condition(
        health.get("ok") is True,
        "Mongo session store debe estar disponible para esta prueba.",
    )

    session = create_session()
    session_id = session["session_id"]

    update_context(
        session,
        {
            "codigo_producto": "300203",
            "familia": "medicion",
        },
    )

    session["last_selected_product_code"] = "300203"
    session["estado_negociacion"] = "producto_seleccionado"

    save_session(session)

    print("\nSESSION_ID:", session_id)
    print("GUARDADA_EN_RAM:", session_id in _SESSIONS)

    assert_condition(
        session_id in _SESSIONS,
        "La sesiÃ³n debe guardarse inicialmente en RAM.",
    )

    # Simula otro worker de Azure:
    # limpiamos RAM local, pero NO borramos Mongo.
    _SESSIONS.clear()

    loaded = get_session(session_id)

    print("RECUPERADA_DESDE_MONGO:", bool(loaded))

    assert_condition(
        loaded is not None,
        "La sesiÃ³n debe recuperarse desde MongoDB despuÃ©s de limpiar RAM.",
    )

    assert_condition(
        loaded.get("context", {}).get("codigo_producto") == "300203",
        "El contexto debe conservar codigo_producto=300203.",
    )

    assert_condition(
        loaded.get("last_selected_product_code") == "300203",
        "La sesiÃ³n debe conservar last_selected_product_code=300203.",
    )

    assert_condition(
        loaded.get("estado_negociacion") == "producto_seleccionado",
        "La sesiÃ³n debe conservar estado_negociacion=producto_seleccionado.",
    )

    # Limpieza final.
    clear_session(session_id)

    print("\nFIN TEST MONGO SESSION STORE âœ…")


if __name__ == "__main__":
    main()

