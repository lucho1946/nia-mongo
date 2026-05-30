# ============================================================
# tests/test_commercial_opportunity_store.py
# ============================================================
# OBJETIVO:
# Validar que NIA persiste oportunidades comerciales en MongoDB
# a partir del commercial_handoff.
#
# Este test cubre:
# 1. Store aislado:
#    commercial_handoff -> commercial_opportunities
#
# 2. Flujo integrado:
#    /chat adapter -> process_message -> commercial_handoff
#    -> commercial_opportunities -> ChatResponse
#
# Alineación con Don Andrés:
# NIA debe dejar una oportunidad comercial accionable para asesor,
# no solo una respuesta conversacional.
# ============================================================

from pathlib import Path
import os
import json

from models.schemas import ChatRequest
from orchestration.chat_response_adapter import process_chat_request
from memory.conversation_memory import clear_session

from memory.commercial_opportunity_store import (
    save_commercial_opportunity,
    get_commercial_opportunity,
    find_commercial_opportunities_by_session,
)


# ============================================================
# CARGA LOCAL DE .env
# ============================================================

def load_local_env():
    """
    Carga variables desde .env para pruebas locales.

    Como este archivo vive en tests/, el .env real está en la raíz.
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


# ============================================================
# UTILIDADES
# ============================================================

def print_section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def assert_condition(condition: bool, message: str):
    """
    Assertion con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def show_json(label: str, data):
    print_section(label)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ============================================================
# CASO 1
# Store aislado de oportunidad comercial
# ============================================================

def run_case_store_direct_commercial_opportunity():
    print_section("CASO 1: store directo de oportunidad comercial")

    handoff = {
        "handoff_id": "cotizacion_test_store_permanent_001",
        "tipo": "cotizacion",
        "estado": "lista_para_asesor",
        "siguiente_paso": "generar_o_enviar_cotizacion",
        "created_at": "2026-05-30T00:00:00+00:00",
        "session_id": "test_store_session_permanent_001",
        "canal": "web",
        "cliente_id": "test_cliente_permanent_001",
        "contact_source": "manual",
        "producto_codigo": "300203",
        "producto_nombre": "Anemometros digitales portatiles Indicadores",
        "producto_marca": "lutron",
        "producto_referencia": "LM-81AM",
        "producto_precio": "$475,114 COP",
        "producto_disponibilidad": "Disponible en Bogotá (6 und)",
        "producto_tiempo_entrega": "1 DIAS",
        "cliente": "Luis Diaz",
        "empresa": "Viaindustrial",
        "correo": "luis2004diazalzate@gmail.com",
        "telefono": None,
        "documento_fiscal": None,
        "nit": None,
        "rut": None,
        "estado_negociacion": "datos_cotizacion_recibidos",
        "commercial_process_id": "process_commercial_spine_v1",
        "commercial_process_state": "cotizacion_lista_para_asesor",
        "ultimo_paso": "cotizacion_lista_para_asesor",
    }

    saved = save_commercial_opportunity(handoff)
    loaded = get_commercial_opportunity("cotizacion_test_store_permanent_001")
    items = find_commercial_opportunities_by_session(
        "test_store_session_permanent_001"
    )

    show_json("SAVED", saved)
    show_json("LOADED", loaded)
    show_json("ITEMS", items)

    assert_condition(saved is not None, "Debe guardar oportunidad comercial.")
    assert_condition(loaded is not None, "Debe leer oportunidad comercial.")

    assert_condition(
        loaded.get("opportunity_id") == "cotizacion_test_store_permanent_001",
        "Debe conservar opportunity_id.",
    )

    assert_condition(
        loaded.get("tipo") == "cotizacion",
        "Debe guardar tipo cotizacion.",
    )

    assert_condition(
        loaded.get("estado") == "lista_para_asesor",
        "Debe guardar estado lista_para_asesor.",
    )

    assert_condition(
        loaded.get("producto_codigo") == "300203",
        "Debe guardar producto 300203.",
    )

    assert_condition(
        loaded.get("producto_precio") == "$475,114 COP",
        "Debe guardar precio.",
    )

    assert_condition(
        loaded.get("producto_disponibilidad") == "Disponible en Bogotá (6 und)",
        "Debe guardar disponibilidad.",
    )

    assert_condition(
        loaded.get("producto_tiempo_entrega") == "1 DIAS",
        "Debe guardar tiempo de entrega.",
    )

    assert_condition(
        loaded.get("cliente") == "Luis Diaz",
        "Debe guardar cliente.",
    )

    assert_condition(
        loaded.get("empresa") == "Viaindustrial",
        "Debe guardar empresa.",
    )

    assert_condition(
        loaded.get("correo") == "luis2004diazalzate@gmail.com",
        "Debe guardar correo.",
    )

    assert_condition(
        len(items) >= 1,
        "Debe listar oportunidades por sesión.",
    )


# ============================================================
# CASO 2
# Flujo integrado web: ChatResponse expone opportunity guardada
# ============================================================

def run_case_integrated_web_opportunity_store():
    print_section("CASO 2: flujo integrado web guarda oportunidad")

    r1 = process_chat_request(ChatRequest(
        mensaje="busco el 300203",
        canal="web",
        cliente_id="test_opportunity_integrated_web_001",
    ))

    r2 = process_chat_request(ChatRequest(
        mensaje="Luis Diaz, ViaIndustrial. luis2004diazalzate@gmail.com",
        session_id=r1.session_id,
        canal="web",
        cliente_id="test_opportunity_integrated_web_001",
    ))

    handoff = r2.commercial_handoff or {}
    opportunity_id = handoff.get("opportunity_id")
    loaded = get_commercial_opportunity(opportunity_id)

    show_json("HANDOFF WEB", handoff)
    show_json("LOADED OPPORTUNITY WEB", loaded)

    assert_condition(handoff, "Debe existir commercial_handoff.")
    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "Debe ser handoff tipo cotizacion.",
    )

    assert_condition(
        handoff.get("opportunity_saved") is True,
        "Debe marcar opportunity_saved=True.",
    )

    assert_condition(
        opportunity_id is not None,
        "Debe exponer opportunity_id.",
    )

    assert_condition(
        loaded is not None,
        "Debe existir oportunidad guardada en Mongo.",
    )

    assert_condition(
        loaded.get("opportunity_id") == opportunity_id,
        "La oportunidad leída debe coincidir con el opportunity_id.",
    )

    assert_condition(
        loaded.get("producto_codigo") == "300203",
        "Debe conservar producto 300203.",
    )

    assert_condition(
        loaded.get("cliente") == "Luis Diaz",
        "Debe guardar cliente.",
    )

    assert_condition(
        loaded.get("empresa") == "Viaindustrial",
        "Debe guardar empresa.",
    )

    assert_condition(
        loaded.get("correo") == "luis2004diazalzate@gmail.com",
        "Debe guardar correo.",
    )

    assert_condition(
        loaded.get("producto_precio") == "$475,114 COP",
        "Debe guardar precio real.",
    )

    clear_session(r1.session_id)


# ============================================================
# CASO 3
# Flujo integrado WhatsApp: guarda oportunidad con teléfono canal
# ============================================================

def run_case_integrated_whatsapp_opportunity_store():
    print_section("CASO 3: flujo integrado whatsapp guarda oportunidad")

    r1 = process_chat_request(ChatRequest(
        mensaje="busco el 300203",
        canal="whatsapp",
        cliente_id="573001234567",
    ))

    handoff = r1.commercial_handoff or {}
    opportunity_id = handoff.get("opportunity_id")
    loaded = get_commercial_opportunity(opportunity_id)

    show_json("HANDOFF WHATSAPP", handoff)
    show_json("LOADED OPPORTUNITY WHATSAPP", loaded)

    assert_condition(handoff, "Debe existir commercial_handoff.")
    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "Debe ser handoff tipo cotizacion.",
    )

    assert_condition(
        handoff.get("opportunity_saved") is True,
        "Debe marcar opportunity_saved=True.",
    )

    assert_condition(
        handoff.get("contact_source") == "channel_phone",
        "Debe marcar contact_source como channel_phone.",
    )

    assert_condition(
        handoff.get("telefono") == "3001234567",
        "Debe guardar teléfono normalizado.",
    )

    assert_condition(
        opportunity_id is not None,
        "Debe exponer opportunity_id.",
    )

    assert_condition(
        loaded is not None,
        "Debe existir oportunidad guardada en Mongo.",
    )

    assert_condition(
        loaded.get("opportunity_id") == opportunity_id,
        "La oportunidad leída debe coincidir con opportunity_id.",
    )

    assert_condition(
        loaded.get("canal") == "whatsapp",
        "Debe guardar canal whatsapp.",
    )

    assert_condition(
        loaded.get("cliente_id") == "573001234567",
        "Debe guardar cliente_id original.",
    )

    assert_condition(
        loaded.get("contact_source") == "channel_phone",
        "Debe guardar contact_source channel_phone.",
    )

    assert_condition(
        loaded.get("telefono") == "3001234567",
        "Debe guardar teléfono del canal.",
    )

    assert_condition(
        loaded.get("producto_codigo") == "300203",
        "Debe conservar producto 300203.",
    )

    assert_condition(
        loaded.get("producto_precio") == "$475,114 COP",
        "Debe conservar precio.",
    )

    clear_session(r1.session_id)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA COMMERCIAL OPPORTUNITY STORE TEST")
    print("=" * 70)

    load_local_env()

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_store_direct_commercial_opportunity()
    run_case_integrated_web_opportunity_store()
    run_case_integrated_whatsapp_opportunity_store()

    print("\nFIN TEST COMMERCIAL OPPORTUNITY STORE ✅")


if __name__ == "__main__":
    main()