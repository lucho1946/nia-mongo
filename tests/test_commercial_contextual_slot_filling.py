# ============================================================
# test_commercial_contextual_slot_filling.py
# ============================================================
# Prueba de slot filling contextual comercial.
#
# Objetivo:
# Validar que NIA interprete respuestas humanas cortas dentro
# del flujo de cotizaciÃ³n:
#
# - "Luisa" -> nombre
# - "Industrias ABC" -> empresa
# - "Se llama Industrias ABC" -> empresa
# - "luisa@abc.com" -> correo
# - "Te estoy dando mi nombre" -> no buscar producto; pedir aclaraciÃ³n
#
# AlineaciÃ³n con Commercial Spine:
# - leer contexto
# - no pedir datos repetidos
# - pedir solo faltantes
# - mantener producto activo
# ============================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from orchestration.nia_orchestrator import process_message
from memory.conversation_memory import get_session, clear_session


def load_local_env() -> None:
    """
    Carga .env para pruebas locales con MongoDB.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"

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
    """
    Assertion simple con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def _response_text(response: Dict[str, Any]) -> str:
    """
    Obtiene texto de respuesta soportando llaves internas y del router.
    """
    return response.get("response") or response.get("respuesta") or ""


def print_step(title: str, response: Dict[str, Any]) -> None:
    """
    Imprime respuesta compacta.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print("session_id:", response.get("session_id"))
    print("estado:", response.get("estado") or response.get("estado_negociacion"))
    print("respuesta:")
    print(_response_text(response))


def print_session(title: str, session: Dict[str, Any]) -> None:
    """
    Imprime estado comercial de sesiÃ³n.
    """
    print("\n" + "-" * 70)
    print(title)
    print("-" * 70)
    print("estado_negociacion:", session.get("estado_negociacion"))
    print("commercial_process_state:", session.get("commercial_process_state"))
    print("datos_faltantes:", session.get("datos_faltantes"))
    print("commercial_data:", session.get("commercial_data"))
    print("last_selected_product_code:", session.get("last_selected_product_code"))


def run_flow_short_name_company_email() -> None:
    """
    Flujo:
    300203 -> cotizar -> Luisa -> Industrias ABC -> correo
    """
    print("\n" + "#" * 70)
    print("FLUJO 1: nombre corto + empresa corta + correo")
    print("#" * 70)

    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    r2 = process_message("quiero cotizar este producto", session_id=session_id)
    r3 = process_message("Luisa", session_id=session_id)
    r4 = process_message("Industrias ABC", session_id=session_id)
    r5 = process_message("luisa@industriasabc.com", session_id=session_id)

    session = get_session(session_id) or {}

    print_step("RESPUESTA INICIO COTIZACIÃ“N", r2)
    print_step("RESPUESTA NOMBRE CORTO", r3)
    print_step("RESPUESTA EMPRESA CORTA", r4)
    print_step("RESPUESTA CORREO", r5)
    print_session("SESSION FINAL FLUJO 1", session)

    assert_condition(
        "iniciar la cotizaciÃ³n" in _response_text(r2),
        "El segundo mensaje debe iniciar cotizaciÃ³n antes de capturar datos.",
    )

    assert_condition(
        "Gracias, Luisa" in _response_text(r3),
        "La respuesta a 'Luisa' debe agradecer a Luisa.",
    )

    assert_condition(
        "Ya tengo nombre" in _response_text(r3),
        "DespuÃ©s de 'Luisa' debe indicar que ya tiene nombre.",
    )

    assert_condition(
        "EncontrÃ© varias opciones" not in _response_text(r4),
        "No debe buscar productos cuando recibe empresa corta.",
    )

    assert_condition(
        "detalle del producto" not in _response_text(r4).lower(),
        "No debe pedir detalle de producto cuando recibe empresa corta.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("nombre_cliente") == "Luisa",
        "Debe guardar nombre_cliente Luisa.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("empresa") == "Industrias Abc",
        "Debe guardar empresa Industrias Abc.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("correo") == "luisa@industriasabc.com",
        "Debe guardar correo luisa@industriasabc.com.",
    )

    assert_condition(
        session.get("last_selected_product_code") == "300203",
        "Debe conservar producto activo 300203 durante todo el flujo.",
    )

    assert_condition(
        session.get("estado_negociacion") == "datos_cotizacion_recibidos",
        "Con nombre, empresa y correo debe quedar datos_cotizacion_recibidos.",
    )

    assert_condition(
        session.get("commercial_process_state") == "cotizacion_lista_para_asesor",
        "Debe quedar en cotizacion_lista_para_asesor.",
    )

    assert_condition(
        session.get("datos_faltantes") == [],
        "No deben quedar datos faltantes.",
    )

    clear_session(session_id)


def run_flow_se_llama_company() -> None:
    """
    Flujo:
    300203 -> cotizar -> Liliana -> Se llama Industrias ABC -> correo
    """
    print("\n" + "#" * 70)
    print("FLUJO 2: empresa con 'Se llama ...'")
    print("#" * 70)

    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    r2 = process_message("quiero cotizar este producto", session_id=session_id)
    r3 = process_message("Liliana", session_id=session_id)
    r4 = process_message("Se llama Industrias ABC", session_id=session_id)
    r5 = process_message("liliana@industriasabc.com", session_id=session_id)

    session = get_session(session_id) or {}

    print_step("RESPUESTA INICIO COTIZACIÃ“N", r2)
    print_step("RESPUESTA NOMBRE", r3)
    print_step("RESPUESTA EMPRESA SE LLAMA", r4)
    print_step("RESPUESTA CORREO", r5)
    print_session("SESSION FINAL FLUJO 2", session)

    assert_condition(
        "iniciar la cotizaciÃ³n" in _response_text(r2),
        "El segundo mensaje debe iniciar cotizaciÃ³n antes de capturar datos.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("nombre_cliente") == "Liliana",
        "Debe guardar nombre_cliente Liliana.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("empresa") == "Industrias Abc",
        "Debe guardar empresa desde 'Se llama Industrias ABC'.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("correo") == "liliana@industriasabc.com",
        "Debe guardar correo liliana@industriasabc.com.",
    )

    assert_condition(
        "EncontrÃ© varias opciones" not in _response_text(r4),
        "No debe buscar productos cuando recibe empresa.",
    )

    assert_condition(
        "detalle del producto" not in _response_text(r4).lower(),
        "No debe pedir detalle del producto cuando recibe empresa.",
    )

    assert_condition(
        session.get("last_selected_product_code") == "300203",
        "Debe conservar producto activo 300203.",
    )

    clear_session(session_id)


def run_flow_meta_reply() -> None:
    """
    Flujo:
    300203 -> cotizar -> Te estoy dando mi nombre -> Luisa
    """
    print("\n" + "#" * 70)
    print("FLUJO 3: respuesta meta no debe caer a bÃºsqueda")
    print("#" * 70)

    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    r2 = process_message("quiero cotizar este producto", session_id=session_id)
    r3 = process_message("Te estoy dando mi nombre", session_id=session_id)
    r4 = process_message("Luisa", session_id=session_id)

    session = get_session(session_id) or {}

    print_step("RESPUESTA INICIO COTIZACIÃ“N", r2)
    print_step("RESPUESTA META", r3)
    print_step("RESPUESTA NOMBRE DESPUÃ‰S DE META", r4)
    print_session("SESSION PARCIAL FLUJO 3", session)

    response_meta = _response_text(r3)

    assert_condition(
        "iniciar la cotizaciÃ³n" in _response_text(r2),
        "El segundo mensaje debe iniciar cotizaciÃ³n antes de capturar datos.",
    )

    assert_condition(
        "nombre" in response_meta.lower(),
        "La respuesta meta debe pedir confirmar el nombre.",
    )

    assert_condition(
        "producto" not in response_meta.lower(),
        "La respuesta meta no debe pedir detalle de producto.",
    )

    assert_condition(
        "EncontrÃ© varias opciones" not in response_meta,
        "La respuesta meta no debe buscar productos.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("nombre_cliente") == "Luisa",
        "DespuÃ©s de 'Luisa' debe guardar nombre_cliente Luisa.",
    )

    assert_condition(
        session.get("estado_negociacion") == "datos_cotizacion_parciales",
        "DespuÃ©s de solo nombre debe quedar datos_cotizacion_parciales.",
    )

    assert_condition(
        session.get("last_selected_product_code") == "300203",
        "Debe conservar producto activo 300203.",
    )

    clear_session(session_id)


def run_flow_phone_direct() -> None:
    """
    Flujo:
    300203 -> cotizar -> Luisa -> Industrias ABC -> 3001234567
    """
    print("\n" + "#" * 70)
    print("FLUJO 4: telÃ©fono directo")
    print("#" * 70)

    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    r2 = process_message("quiero cotizar este producto", session_id=session_id)
    process_message("Luisa", session_id=session_id)
    process_message("Industrias ABC", session_id=session_id)
    r5 = process_message("3001234567", session_id=session_id)

    session = get_session(session_id) or {}

    print_step("RESPUESTA INICIO COTIZACIÃ“N", r2)
    print_step("RESPUESTA TELÃ‰FONO", r5)
    print_session("SESSION FINAL FLUJO 4", session)

    assert_condition(
        "iniciar la cotizaciÃ³n" in _response_text(r2),
        "El segundo mensaje debe iniciar cotizaciÃ³n antes de capturar datos.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("telefono") == "3001234567",
        "Debe guardar telÃ©fono 3001234567.",
    )

    assert_condition(
        session.get("estado_negociacion") == "datos_cotizacion_recibidos",
        "Con nombre, empresa y telÃ©fono debe quedar datos_cotizacion_recibidos.",
    )

    assert_condition(
        session.get("datos_faltantes") == [],
        "No deben quedar datos faltantes con telÃ©fono.",
    )

    assert_condition(
        session.get("last_selected_product_code") == "300203",
        "Debe conservar producto activo 300203.",
    )

    clear_session(session_id)


def main() -> None:
    print("\n" + "=" * 70)
    print("NIA COMMERCIAL CONTEXTUAL SLOT FILLING TEST")
    print("=" * 70)

    load_local_env()

    assert_condition(
        bool(os.getenv("MONGO_CONNECTION_STRING")),
        "MONGO_CONNECTION_STRING debe estar configurado para esta prueba.",
    )

    run_flow_short_name_company_email()
    run_flow_se_llama_company()
    run_flow_meta_reply()
    run_flow_phone_direct()

    print("\nFIN TEST COMMERCIAL CONTEXTUAL SLOT FILLING âœ…")


if __name__ == "__main__":
    main()


