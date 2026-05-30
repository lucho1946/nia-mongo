# ============================================================
# test_chat_response_handoff_adapter.py
# ============================================================
# OBJETIVO:
# Validar que el adapter público del endpoint /chat expone
# correctamente el commercial_handoff generado por el orquestador.
#
# Este test NO prueba directamente process_message().
# Este test prueba:
#
# ChatRequest
#   -> process_chat_request()
#   -> ChatResponse
#
# Es decir, valida el contrato público que consumen:
# - frontend
# - WhatsApp futuro
# - Bitrix
# - CRM
# - panel comercial
#
# Alineación con Don Andrés:
# NIA debe dejar una oportunidad comercial accionable, no solo
# una respuesta conversacional.
# ============================================================

from pathlib import Path
import os
import json

from models.schemas import ChatRequest
from orchestration.chat_response_adapter import process_chat_request
from memory.conversation_memory import clear_session


# ============================================================
# CARGA LOCAL DE .env
# ============================================================

def load_local_env():
    """
    Carga variables desde .env para pruebas locales.

    Necesario para:
    - MONGO_CONNECTION_STRING
    - catálogo real
    - sesiones persistentes
    """
    env_path = Path(__file__).resolve().parent / ".env"

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


# ============================================================
# UTILIDADES DE TEST
# ============================================================

def print_section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def assert_condition(condition: bool, message: str):
    """
    Assertion con mensaje claro para diagnóstico rápido.
    """
    if not condition:
        raise AssertionError(message)


def show_response(label: str, response):
    print_section(label)
    print("session_id:", response.session_id)
    print("estado:", response.estado)
    print("estado_negociacion:", response.estado_negociacion)
    print("commercial_process_state:", response.commercial_process_state)
    print("siguiente_paso:", response.siguiente_paso)
    print("datos_faltantes:", response.datos_faltantes)
    print("respuesta:")
    print(response.respuesta)


def show_handoff(label: str, handoff):
    print_section(label)
    print(json.dumps(handoff, indent=2, ensure_ascii=False))


# ============================================================
# CASO 1
# El adapter debe exponer handoff de cotización
# ============================================================

def run_case_adapter_exposes_quote_handoff():
    print_section("CASO 1: adapter expone commercial_handoff de cotización")

    r1 = process_chat_request(ChatRequest(
        mensaje="busco el 300203",
        canal="web",
        cliente_id="test_adapter_handoff_001",
    ))

    r2 = process_chat_request(ChatRequest(
        mensaje="Luis Diaz, ViaIndustrial. luis2004diazalzate@gmail.com",
        session_id=r1.session_id,
        canal="web",
        cliente_id="test_adapter_handoff_001",
    ))

    show_response("RESPUESTA R1", r1)
    show_response("RESPUESTA R2", r2)
    show_handoff("COMMERCIAL_HANDOFF R2", r2.commercial_handoff)

    assert_condition(
        "Encontré el producto exacto" in r1.respuesta,
        "R1 debe encontrar el producto exacto.",
    )

    assert_condition(
        "Para continuar con la cotización" in r1.respuesta,
        "R1 debe pedir datos comerciales automáticamente.",
    )

    assert_condition(
        r2.estado_negociacion == "datos_cotizacion_recibidos",
        "R2 debe quedar en datos_cotizacion_recibidos.",
    )

    assert_condition(
        r2.commercial_process_state == "cotizacion_lista_para_asesor",
        "R2 debe quedar en cotizacion_lista_para_asesor.",
    )

    assert_condition(
        r2.datos_faltantes == [],
        "R2 no debe tener datos faltantes.",
    )

    assert_condition(
        r2.commercial_handoff is not None,
        "ChatResponse debe exponer commercial_handoff.",
    )

    handoff = r2.commercial_handoff

    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "El handoff debe ser tipo cotizacion.",
    )

    assert_condition(
        handoff.get("estado") == "lista_para_asesor",
        "El handoff debe quedar lista_para_asesor.",
    )

    assert_condition(
        handoff.get("siguiente_paso") == "generar_o_enviar_cotizacion",
        "El siguiente paso debe ser generar_o_enviar_cotizacion.",
    )

    assert_condition(
        handoff.get("producto_codigo") == "300203",
        "El handoff debe conservar producto 300203.",
    )

    assert_condition(
        handoff.get("producto_nombre") == "Anemometros digitales portatiles Indicadores",
        "El handoff debe conservar nombre del producto.",
    )

    assert_condition(
        handoff.get("producto_marca") == "lutron",
        "El handoff debe conservar marca.",
    )

    assert_condition(
        handoff.get("producto_referencia") == "LM-81AM",
        "El handoff debe conservar referencia.",
    )

    assert_condition(
        handoff.get("producto_precio") == "$475,114 COP",
        "El handoff debe conservar precio.",
    )

    assert_condition(
        handoff.get("producto_disponibilidad") == "Disponible en Bogotá (6 und)",
        "El handoff debe conservar disponibilidad.",
    )

    assert_condition(
        handoff.get("producto_tiempo_entrega") == "1 DIAS",
        "El handoff debe conservar tiempo de entrega.",
    )

    assert_condition(
        handoff.get("cliente") == "Luis Diaz",
        "El handoff debe guardar cliente.",
    )

    assert_condition(
        handoff.get("empresa") == "Viaindustrial",
        "El handoff debe guardar empresa.",
    )

    assert_condition(
        handoff.get("correo") == "luis2004diazalzate@gmail.com",
        "El handoff debe guardar correo.",
    )

    assert_condition(
        handoff.get("canal") == "web",
        "El handoff debe conservar canal web.",
    )

    assert_condition(
        handoff.get("cliente_id") == "test_adapter_handoff_001",
        "El handoff debe conservar cliente_id.",
    )

    clear_session(r1.session_id)


# ============================================================
# CASO 2
# El adapter debe exponer handoff con teléfono del canal
# ============================================================

def run_case_adapter_exposes_channel_phone_handoff():
    print_section("CASO 2: adapter expone handoff con teléfono del canal")

    r1 = process_chat_request(ChatRequest(
        mensaje="busco el 300203",
        canal="whatsapp",
        cliente_id="573001234567",
    ))

    show_response("RESPUESTA WHATSAPP", r1)
    show_handoff("COMMERCIAL_HANDOFF WHATSAPP", r1.commercial_handoff)

    assert_condition(
        "Encontré el producto exacto" in r1.respuesta,
        "Debe encontrar producto exacto.",
    )

    assert_condition(
        "este mismo número de contacto" in r1.respuesta,
        "Debe indicar que puede enviar cotización al número del canal.",
    )

    assert_condition(
        r1.commercial_handoff is not None,
        "ChatResponse debe exponer commercial_handoff con teléfono del canal.",
    )

    handoff = r1.commercial_handoff

    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "El handoff con teléfono debe ser tipo cotizacion.",
    )

    assert_condition(
        handoff.get("contact_source") == "channel_phone",
        "El contact_source debe ser channel_phone.",
    )

    assert_condition(
        handoff.get("telefono") == "3001234567",
        "Debe guardar el teléfono normalizado del canal.",
    )

    assert_condition(
        handoff.get("canal") == "whatsapp",
        "Debe conservar canal whatsapp.",
    )

    assert_condition(
        handoff.get("cliente_id") == "573001234567",
        "Debe conservar cliente_id original.",
    )

    assert_condition(
        handoff.get("producto_codigo") == "300203",
        "Debe conservar producto 300203.",
    )

    assert_condition(
        handoff.get("producto_precio") == "$475,114 COP",
        "Debe conservar precio en handoff con teléfono.",
    )

    assert_condition(
        handoff.get("producto_disponibilidad") == "Disponible en Bogotá (6 und)",
        "Debe conservar disponibilidad en handoff con teléfono.",
    )

    assert_condition(
        handoff.get("producto_tiempo_entrega") == "1 DIAS",
        "Debe conservar entrega en handoff con teléfono.",
    )

    clear_session(r1.session_id)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA CHAT RESPONSE HANDOFF ADAPTER TEST")
    print("=" * 70)

    load_local_env()

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_adapter_exposes_quote_handoff()
    run_case_adapter_exposes_channel_phone_handoff()

    print("\nFIN TEST CHAT RESPONSE HANDOFF ADAPTER ✅")


if __name__ == "__main__":
    main()