# ============================================================
# test_commercial_state_engine.py
# ============================================================
# Prueba del motor de estados comercial.
#
# Objetivo:
# - Validar el mapeo entre estados internos actuales de NIA
#   y estados oficiales del Commercial Spine.
# - Validar cálculo de datos faltantes.
# - Validar actualización de sesión con:
#   commercial_process_state
#   ultimo_paso
#   siguiente_paso
#   datos_faltantes
# ============================================================

from __future__ import annotations

import json
from typing import Any, Dict

from orchestration.commercial_state_engine import (
    get_commercial_spine_states,
    map_internal_state_to_spine_state,
    get_next_spine_state,
    calculate_quote_missing_fields,
    has_complete_minimum_quote_data,
    build_commercial_process_snapshot,
    update_commercial_process_state,
    summarize_commercial_process_state,
)


def assert_condition(condition: bool, message: str) -> None:
    """
    Assertion simple con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def build_base_session() -> Dict[str, Any]:
    """
    Crea una sesión mínima para pruebas del state engine.
    """
    return {
        "session_id": "test_state_engine",
        "estado_negociacion": None,
        "intent": None,
        "last_selected_product": None,
        "last_selected_product_code": None,
        "commercial_data": {
            "nombre_cliente": None,
            "empresa": None,
            "correo": None,
            "telefono": None,
            "cantidad": None,
            "presupuesto_aproximado": None,
            "fecha_estimada_compra": None,
        },
    }


def main() -> None:
    print("\n" + "=" * 70)
    print("NIA COMMERCIAL STATE ENGINE TEST")
    print("=" * 70)

    # ========================================================
    # 1. El Commercial Spine debe tener estados cargados
    # ========================================================

    states = get_commercial_spine_states()

    print("\nESTADOS CARGADOS:")
    for state in states:
        print("-", state)

    assert_condition(
        "producto_identificado" in states,
        "El Spine debe contener producto_identificado.",
    )

    assert_condition(
        "preparar_cotizacion" in states,
        "El Spine debe contener preparar_cotizacion.",
    )

    assert_condition(
        "pedir_datos_faltantes_cotizacion" in states,
        "El Spine debe contener pedir_datos_faltantes_cotizacion.",
    )

    assert_condition(
        "cotizacion_lista_para_asesor" in states,
        "El Spine debe contener cotizacion_lista_para_asesor.",
    )

    # ========================================================
    # 2. Mapeo de estados internos actuales
    # ========================================================

    mappings = {
        "producto_seleccionado": "producto_identificado",
        "producto_identificado": "producto_identificado",
        "cotizacion_en_proceso": "preparar_cotizacion",
        "cotizacion_pendiente": "preparar_cotizacion",
        "datos_cotizacion_parciales": "pedir_datos_faltantes_cotizacion",
        "datos_cotizacion_recibidos": "cotizacion_lista_para_asesor",
    }

    print("\nMAPEOS:")
    for internal_state, expected_spine_state in mappings.items():
        actual = map_internal_state_to_spine_state(internal_state)

        print(f"- {internal_state} -> {actual}")

        assert_condition(
            actual == expected_spine_state,
            f"{internal_state} debe mapear a {expected_spine_state}, pero dio {actual}.",
        )

    # ========================================================
    # 3. Siguiente paso según estado
    # ========================================================

    assert_condition(
        get_next_spine_state("producto_identificado") == "preparar_cotizacion",
        "producto_identificado debe avanzar hacia preparar_cotizacion.",
    )

    assert_condition(
        get_next_spine_state("preparar_cotizacion") == "pedir_datos_faltantes_cotizacion",
        "preparar_cotizacion debe avanzar hacia pedir_datos_faltantes_cotizacion.",
    )

    assert_condition(
        get_next_spine_state("datos_inexistente") == "esperar_respuesta_cliente",
        "Estado desconocido debe caer en esperar_respuesta_cliente.",
    )

    # ========================================================
    # 4. Sin producto ni datos: faltan producto, nombre, empresa y contacto
    # ========================================================

    session = build_base_session()

    missing = calculate_quote_missing_fields(session)

    print("\nFALTANTES SIN DATOS:")
    print(missing)

    assert_condition(
        "producto" in missing,
        "Si no hay producto activo, debe faltar producto.",
    )

    assert_condition(
        "nombre" in missing,
        "Si no hay nombre, debe faltar nombre.",
    )

    assert_condition(
        "empresa" in missing,
        "Si no hay empresa, debe faltar empresa.",
    )

    assert_condition(
        "correo o teléfono" in missing,
        "Si no hay contacto, debe faltar correo o teléfono.",
    )

    assert_condition(
        has_complete_minimum_quote_data(session) is False,
        "Sin datos no debe estar completa la cotización mínima.",
    )

    # ========================================================
    # 5. Producto activo sin datos comerciales
    # ========================================================

    session = build_base_session()
    session["estado_negociacion"] = "producto_seleccionado"
    session["last_selected_product"] = {
        "codigo": "300203",
        "nombre": "Anemometros digitales portatiles Indicadores",
        "marca": "lutron",
    }
    session["last_selected_product_code"] = "300203"

    snapshot = build_commercial_process_snapshot(
        session,
        detected_intent="codigo_producto",
    )

    print("\nSNAPSHOT PRODUCTO ACTIVO:")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))

    assert_condition(
        snapshot["commercial_process_state"] == "producto_identificado",
        "producto_seleccionado debe quedar como producto_identificado.",
    )

    assert_condition(
        snapshot["siguiente_paso"] == "preparar_cotizacion",
        "Después de producto_identificado debe seguir preparar_cotizacion.",
    )

    assert_condition(
        snapshot["producto_activo_codigo"] == "300203",
        "Debe conservar código de producto activo.",
    )

    # ========================================================
    # 6. Cotización en proceso con datos parciales
    # ========================================================

    session["estado_negociacion"] = "datos_cotizacion_parciales"
    session["commercial_data"] = {
        "nombre_cliente": "Andrea",
        "empresa": None,
        "correo": None,
        "telefono": None,
        "cantidad": None,
        "presupuesto_aproximado": None,
        "fecha_estimada_compra": None,
    }

    update_commercial_process_state(
        session,
        detected_intent="comercial",
    )

    print("\nSESSION DATOS PARCIALES:")
    print(json.dumps(session, ensure_ascii=False, indent=2, default=str))

    assert_condition(
        session["commercial_process_state"] == "pedir_datos_faltantes_cotizacion",
        "datos parciales deben quedar en pedir_datos_faltantes_cotizacion.",
    )

    assert_condition(
        "empresa" in session["datos_faltantes"],
        "Debe faltar empresa.",
    )

    assert_condition(
        "correo o teléfono" in session["datos_faltantes"],
        "Debe faltar correo o teléfono.",
    )

    assert_condition(
        session["siguiente_paso"] == "esperar_respuesta_cliente",
        "Después de pedir faltantes debe esperar respuesta del cliente.",
    )

    # ========================================================
    # 7. Datos mínimos completos
    # ========================================================

    session["estado_negociacion"] = "datos_cotizacion_recibidos"
    session["commercial_data"] = {
        "nombre_cliente": "Carlos",
        "empresa": "Industrias ABC",
        "correo": "carlos@abc.com",
        "telefono": None,
        "cantidad": None,
        "presupuesto_aproximado": None,
        "fecha_estimada_compra": None,
    }

    update_commercial_process_state(
        session,
        detected_intent="comercial",
    )

    print("\nSESSION DATOS COMPLETOS:")
    print(json.dumps(session, ensure_ascii=False, indent=2, default=str))

    assert_condition(
        session["commercial_process_state"] == "cotizacion_lista_para_asesor",
        "datos completos deben quedar en cotizacion_lista_para_asesor.",
    )

    assert_condition(
        session["datos_faltantes"] == [],
        "Con datos mínimos completos no deben faltar datos.",
    )

    assert_condition(
        session["siguiente_paso"] == "validando_cumplimiento",
        "Después de cotizacion_lista_para_asesor debe seguir validando_cumplimiento.",
    )

    assert_condition(
        has_complete_minimum_quote_data(session) is True,
        "Con producto, nombre, empresa y correo debe estar completa la cotización mínima.",
    )

    # ========================================================
    # 8. Resumen legible
    # ========================================================

    summary = summarize_commercial_process_state(session)

    print("\nRESUMEN:")
    print(summary)

    assert_condition(
        "cotizacion_lista_para_asesor" in summary,
        "El resumen debe mencionar cotizacion_lista_para_asesor.",
    )

    print("\nFIN TEST COMMERCIAL STATE ENGINE ✅")


if __name__ == "__main__":
    main()