# ============================================================
# test_commercial_state_flow_integration.py
# ============================================================
# Prueba de integración entre:
# - nia_orchestrator.py
# - commercial_continuity.py
# - commercial_data_extractor.py
# - commercial_state_engine.py
# - conversation_memory.py
#
# Objetivo:
# Validar que el flujo real de chat actualice en sesión:
# - commercial_process_id
# - commercial_process_state
# - ultimo_paso
# - siguiente_paso
# - datos_faltantes
# - intencion_actual
#
# IMPORTANTE:
# Este test necesita MONGO_CONNECTION_STRING porque ejecuta el
# flujo real de búsqueda/catálogo y memoria.
# ============================================================

from __future__ import annotations

import json
import os
from pathlib import Path


# ============================================================
# CARGA DE VARIABLES DE ENTORNO
# ============================================================

def load_local_env() -> None:
    """
    Carga variables desde .env para pruebas locales.

    Este test ejecuta process_message() directamente, sin levantar FastAPI.
    Por eso debemos cargar MONGO_CONNECTION_STRING manualmente antes de
    importar módulos internos que usan MongoDB.
    """
    env_path = Path(__file__).resolve().parent / ".env"

    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


# Cargamos .env antes de importar módulos del proyecto.
load_local_env()


from orchestration.nia_orchestrator import process_message
from memory.conversation_memory import get_session, clear_session


# ============================================================
# UTILIDADES DE TEST
# ============================================================

def assert_condition(condition: bool, message: str) -> None:
    """
    Assertion simple con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def print_session_state(title: str, session: dict) -> None:
    """
    Imprime una vista compacta del estado comercial.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

    compact = {
        "session_id": session.get("session_id"),
        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes": session.get("datos_faltantes"),
        "intencion_actual": session.get("intencion_actual"),
        "last_selected_product_code": session.get("last_selected_product_code"),
        "commercial_data": session.get("commercial_data"),
    }

    print(json.dumps(compact, ensure_ascii=False, indent=2, default=str))


def get_required_env_value(key: str) -> str:
    """
    Obtiene variable obligatoria de entorno.
    """
    value = os.getenv(key, "").strip()

    assert_condition(
        bool(value),
        f"{key} debe estar configurado para esta prueba de integración.",
    )

    return value


# ============================================================
# TEST PRINCIPAL
# ============================================================

def main() -> None:
    print("\n" + "=" * 70)
    print("NIA COMMERCIAL STATE FLOW INTEGRATION TEST")
    print("=" * 70)

    # --------------------------------------------------------
    # Validación de entorno
    # --------------------------------------------------------
    # Esta prueba usa el flujo real:
    # - búsqueda por código
    # - sesión
    # - memoria
    # - catálogo
    #
    # Por eso necesita MongoDB configurado.
    # --------------------------------------------------------
    get_required_env_value("MONGO_CONNECTION_STRING")

    # ========================================================
    # FLUJO 1:
    # Producto -> cotización -> datos parciales
    # ========================================================

    r1 = process_message(
        message="busco el producto 300203",
        session_id=None,
    )

    session_id = r1.get("session_id")

    assert_condition(
        bool(session_id),
        "Debe existir session_id después de buscar producto.",
    )

    assert_condition(
        r1.get("cards"),
        "La búsqueda por código 300203 debe devolver producto.",
    )

    process_message(
        message="quiero cotizar este producto",
        session_id=session_id,
    )

    session = get_session(session_id) or {}

    print_session_state(
        "DESPUÉS DE INICIAR COTIZACIÓN",
        session,
    )

    assert_condition(
        session.get("estado_negociacion") == "cotizacion_en_proceso",
        "Al iniciar cotización, estado_negociacion debe ser cotizacion_en_proceso.",
    )

    assert_condition(
        session.get("commercial_process_id") == "process_commercial_spine_v1",
        "Debe guardar commercial_process_id.",
    )

    assert_condition(
        session.get("commercial_process_state") == "preparar_cotizacion",
        "cotizacion_en_proceso debe mapear a preparar_cotizacion.",
    )

    assert_condition(
        session.get("ultimo_paso") == "preparar_cotizacion",
        "ultimo_paso debe ser preparar_cotizacion.",
    )

    assert_condition(
        session.get("siguiente_paso") == "pedir_datos_faltantes_cotizacion",
        "Después de preparar_cotizacion debe seguir pedir_datos_faltantes_cotizacion.",
    )

    assert_condition(
        "nombre" in session.get("datos_faltantes", []),
        "Debe faltar nombre al iniciar cotización.",
    )

    assert_condition(
        "empresa" in session.get("datos_faltantes", []),
        "Debe faltar empresa al iniciar cotización.",
    )

    assert_condition(
        "correo o teléfono" in session.get("datos_faltantes", []),
        "Debe faltar correo o teléfono al iniciar cotización.",
    )

    process_message(
        message="Me llamo Andrea",
        session_id=session_id,
    )

    session = get_session(session_id) or {}

    print_session_state(
        "DESPUÉS DE DATOS PARCIALES",
        session,
    )

    assert_condition(
        session.get("estado_negociacion") == "datos_cotizacion_parciales",
        "Con datos parciales debe quedar datos_cotizacion_parciales.",
    )

    assert_condition(
        session.get("commercial_process_state") == "pedir_datos_faltantes_cotizacion",
        "datos parciales deben mapear a pedir_datos_faltantes_cotizacion.",
    )

    assert_condition(
        session.get("ultimo_paso") == "pedir_datos_faltantes_cotizacion",
        "ultimo_paso debe ser pedir_datos_faltantes_cotizacion.",
    )

    assert_condition(
        session.get("siguiente_paso") == "esperar_respuesta_cliente",
        "Después de pedir faltantes debe esperar respuesta del cliente.",
    )

    assert_condition(
        "empresa" in session.get("datos_faltantes", []),
        "Con solo nombre debe seguir faltando empresa.",
    )

    assert_condition(
        "correo o teléfono" in session.get("datos_faltantes", []),
        "Con solo nombre debe seguir faltando correo o teléfono.",
    )

    assert_condition(
        session.get("commercial_data", {}).get("nombre_cliente") == "Andrea",
        "Debe guardar nombre_cliente Andrea.",
    )

    clear_session(session_id)

    # ========================================================
    # FLUJO 2:
    # Producto -> cotización -> datos completos
    # ========================================================

    r4 = process_message(
        message="busco el producto 300203",
        session_id=None,
    )

    session_id_2 = r4.get("session_id")

    assert_condition(
        bool(session_id_2),
        "Debe existir session_id en el segundo flujo.",
    )

    assert_condition(
        r4.get("cards"),
        "La segunda búsqueda por código 300203 debe devolver producto.",
    )

    process_message(
        message="quiero cotizar este producto",
        session_id=session_id_2,
    )

    r6 = process_message(
        message="Soy Carlos de Industrias ABC, mi correo es carlos@abc.com",
        session_id=session_id_2,
    )

    session_2 = get_session(session_id_2) or {}

    print_session_state(
        "DESPUÉS DE DATOS COMPLETOS",
        session_2,
    )

    assert_condition(
        "Gracias, Carlos" in r6.get("response", ""),
        "La respuesta debe saludar correctamente a Carlos.",
    )

    assert_condition(
        session_2.get("estado_negociacion") == "datos_cotizacion_recibidos",
        "Con datos completos debe quedar datos_cotizacion_recibidos.",
    )

    assert_condition(
        session_2.get("commercial_process_id") == "process_commercial_spine_v1",
        "Debe guardar commercial_process_id en datos completos.",
    )

    assert_condition(
        session_2.get("commercial_process_state") == "cotizacion_lista_para_asesor",
        "datos completos deben mapear a cotizacion_lista_para_asesor.",
    )

    assert_condition(
        session_2.get("ultimo_paso") == "cotizacion_lista_para_asesor",
        "ultimo_paso debe ser cotizacion_lista_para_asesor.",
    )

    assert_condition(
        session_2.get("siguiente_paso") == "validando_cumplimiento",
        "Después de cotizacion_lista_para_asesor debe seguir validando_cumplimiento.",
    )

    assert_condition(
        session_2.get("datos_faltantes") == [],
        "Con producto, nombre, empresa y correo no deben faltar datos mínimos.",
    )

    assert_condition(
        session_2.get("commercial_data", {}).get("nombre_cliente") == "Carlos",
        "Debe guardar nombre_cliente Carlos.",
    )

    assert_condition(
        session_2.get("commercial_data", {}).get("empresa") == "Industrias Abc",
        "Debe guardar empresa Industrias Abc.",
    )

    assert_condition(
        session_2.get("commercial_data", {}).get("correo") == "carlos@abc.com",
        "Debe guardar correo carlos@abc.com.",
    )

    assert_condition(
        session_2.get("last_selected_product_code") == "300203",
        "Debe conservar last_selected_product_code 300203.",
    )

    clear_session(session_id_2)

    print("\nFIN TEST COMMERCIAL STATE FLOW INTEGRATION ✅")


if __name__ == "__main__":
    main()