# ============================================================
# test_commercial_handoff_flow.py
# ============================================================
# OBJETIVO:
# Validar que NIA construye un handoff comercial estructurado
# cuando llega a estados accionables para asesor:
#
# - cotizaciÃ³n lista para asesor
# - proforma lista para asesor
#
# Este test asegura que:
# 1. Producto exacto inicia cotizaciÃ³n automÃ¡ticamente.
# 2. La captura de datos comerciales genera handoff tipo cotizaciÃ³n.
# 3. El seguimiento de cotizaciÃ³n conserva contexto.
# 4. La intenciÃ³n de compra activa proforma.
# 5. La captura de NIT genera handoff tipo proforma.
# 6. La proforma conserva precio/disponibilidad originales.
#
# AlineaciÃ³n con Don AndrÃ©s:
# - NIA no solo conversa.
# - NIA debe dejar una oportunidad comercial clara y accionable.
# - La oportunidad debe incluir producto, cliente, contacto,
#   documento fiscal, estado y siguiente paso.
# ============================================================

from pathlib import Path
import os
import json


# ============================================================
# CARGA LOCAL DE .env
# ============================================================

def load_local_env():
    """
    Carga variables desde .env para pruebas locales.

    Necesario para:
    - MONGO_CONNECTION_STRING
    - acceso a catÃ¡logo real
    - persistencia de sesiones
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


load_local_env()


from orchestration.nia_orchestrator import process_message
from memory.conversation_memory import get_session, clear_session


# ============================================================
# UTILIDADES DE TEST
# ============================================================

def print_section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_case(title: str):
    print("\n" + "#" * 70)
    print(title)
    print("#" * 70)


def response_text(response: dict) -> str:
    """
    Obtiene texto de respuesta de forma compatible con:
    - process_message -> response
    - adapter/API -> respuesta
    """
    return response.get("response") or response.get("respuesta") or ""



def normalize_text(value: str) -> str:
    """
    Normaliza texto para comparaciones en tests.
    Evita fallos por tildes o codificación de consola.
    """
    import unicodedata

    value = "" if value is None else str(value)
    value = value.lower().strip()

    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )

    return value


def assert_condition(condition: bool, message: str):
    """
    Assertion con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def show_response(label: str, response: dict):
    print_section(label)
    print("session_id:", response.get("session_id"))
    print("estado:", response.get("estado_negociacion") or response.get("estado"))
    print("respuesta:")
    print(response_text(response))


def show_handoff(label: str, handoff: dict):
    print_section(label)
    print(json.dumps(handoff, indent=2, ensure_ascii=False))


def run_full_handoff_flow():
    """
    Ejecuta el flujo completo:
    producto exacto -> datos comerciales -> cotizaciÃ³n handoff
    -> seguimiento -> compra -> NIT -> proforma handoff.
    """
    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    r2 = process_message(
        "Luis Diaz, ViaIndustrial. luis2004diazalzate@gmail.com",
        session_id=session_id,
    )

    session_after_quote = get_session(session_id) or {}
    handoff_quote = session_after_quote.get("commercial_handoff") or {}

    r3 = process_message(
        "Ya recibÃ­ la cotizaciÃ³n",
        session_id=session_id,
    )

    r4 = process_message(
        "quiero comprar",
        session_id=session_id,
    )

    r5 = process_message(
        "Mi NIT es 900123456-7",
        session_id=session_id,
    )

    session_after_proforma = get_session(session_id) or {}
    handoff_proforma = session_after_proforma.get("commercial_handoff") or {}

    return {
        "session_id": session_id,
        "responses": {
            "r1": r1,
            "r2": r2,
            "r3": r3,
            "r4": r4,
            "r5": r5,
        },
        "session_after_quote": session_after_quote,
        "session_after_proforma": session_after_proforma,
        "handoff_quote": handoff_quote,
        "handoff_proforma": handoff_proforma,
    }


# ============================================================
# CASO 1
# Producto exacto inicia cotizaciÃ³n automÃ¡ticamente
# ============================================================

def run_case_exact_product_starts_quote():
    print_case("CASO 1: producto exacto inicia cotizaciÃ³n automÃ¡tica")

    data = run_full_handoff_flow()
    r1 = data["responses"]["r1"]
    session_after_quote = data["session_after_quote"]

    show_response("RESPUESTA PRODUCTO EXACTO", r1)

    assert_condition(
        "encontre el producto exacto" in normalize_text(response_text(r1)),
        "Debe encontrar el producto exacto.",
    )

    assert_condition(
        "para continuar con la cotizacion" in normalize_text(response_text(r1)),
        "DespuÃ©s de encontrar producto exacto debe pedir datos para cotizaciÃ³n.",
    )

    assert_condition(
        data["session_after_proforma"].get("last_selected_product_code") == "300203",
        "Debe conservar producto activo 300203.",
    )

    assert_condition(
        session_after_quote.get("commercial_handoff") is not None,
        "DespuÃ©s de capturar datos comerciales debe existir commercial_handoff.",
    )

    clear_session(data["session_id"])


# ============================================================
# CASO 2
# Handoff de cotizaciÃ³n
# ============================================================

def run_case_quote_handoff():
    print_case("CASO 2: handoff tipo cotizaciÃ³n")

    data = run_full_handoff_flow()
    handoff = data["handoff_quote"]

    show_handoff("HANDOFF COTIZACIÃ“N", handoff)

    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "El handoff despuÃ©s de datos comerciales debe ser tipo cotizacion.",
    )

    assert_condition(
        handoff.get("estado") == "lista_para_asesor",
        "El handoff de cotizaciÃ³n debe quedar lista_para_asesor.",
    )

    assert_condition(
        handoff.get("siguiente_paso") == "generar_o_enviar_cotizacion",
        "El siguiente paso de cotizaciÃ³n debe ser generar_o_enviar_cotizacion.",
    )

    assert_condition(
        handoff.get("producto_codigo") == "300203",
        "La cotizaciÃ³n debe conservar producto 300203.",
    )

    assert_condition(
        handoff.get("producto_nombre") == "Anemometros digitales portatiles Indicadores",
        "Debe conservar nombre del producto.",
    )

    assert_condition(
        handoff.get("producto_marca") == "lutron",
        "Debe conservar marca del producto.",
    )

    assert_condition(
        handoff.get("producto_referencia") == "LM-81AM",
        "Debe conservar referencia del producto.",
    )

    assert_condition(
        handoff.get("producto_precio") == "$475,114 COP",
        "Debe conservar precio original en cotizaciÃ³n.",
    )

    assert_condition(
        normalize_text(handoff.get("producto_disponibilidad")) == "disponible en bogota (6 und)",
        "Debe conservar disponibilidad original en cotizaciÃ³n.",
    )

    assert_condition(
        handoff.get("producto_tiempo_entrega") == "1 DIAS",
        "Debe conservar tiempo de entrega.",
    )

    assert_condition(
        handoff.get("cliente") == "Luis Diaz",
        "Debe guardar cliente Luis Diaz.",
    )

    assert_condition(
        handoff.get("empresa") == "Viaindustrial",
        "Debe guardar empresa Viaindustrial.",
    )

    assert_condition(
        handoff.get("correo") == "luis2004diazalzate@gmail.com",
        "Debe guardar correo.",
    )

    assert_condition(
        handoff.get("commercial_process_state") == "cotizacion_lista_para_asesor",
        "El estado del proceso debe quedar cotizacion_lista_para_asesor.",
    )

    clear_session(data["session_id"])


# ============================================================
# CASO 3
# Handoff de proforma
# ============================================================

def run_case_proforma_handoff():
    print_case("CASO 3: handoff tipo proforma")

    data = run_full_handoff_flow()
    r5 = data["responses"]["r5"]
    handoff = data["handoff_proforma"]

    show_response("RESPUESTA CAPTURA NIT", r5)
    show_handoff("HANDOFF PROFORMA", handoff)

    assert_condition(
        handoff.get("tipo") == "proforma",
        "El handoff despuÃ©s de capturar NIT debe ser tipo proforma.",
    )

    assert_condition(
        handoff.get("estado") == "lista_para_asesor",
        "El handoff de proforma debe quedar lista_para_asesor.",
    )

    assert_condition(
        handoff.get("siguiente_paso") == "revision_asesor",
        "El siguiente paso de proforma debe ser revision_asesor.",
    )

    assert_condition(
        handoff.get("producto_codigo") == "300203",
        "La proforma debe conservar producto 300203.",
    )

    assert_condition(
        handoff.get("cliente") == "Luis Diaz",
        "La proforma debe conservar cliente.",
    )

    assert_condition(
        handoff.get("empresa") == "Viaindustrial",
        "La proforma debe conservar empresa.",
    )

    assert_condition(
        handoff.get("correo") == "luis2004diazalzate@gmail.com",
        "La proforma debe conservar correo.",
    )

    assert_condition(
        handoff.get("documento_fiscal") == "900123456-7",
        "Debe guardar documento fiscal.",
    )

    assert_condition(
        handoff.get("nit") == "900123456-7",
        "Debe guardar NIT.",
    )

    assert_condition(
        handoff.get("commercial_process_state") == "proforma_lista_para_asesor",
        "El estado del proceso debe quedar proforma_lista_para_asesor.",
    )

    clear_session(data["session_id"])


# ============================================================
# CASO 4
# Proforma conserva precio y disponibilidad
# ============================================================

def run_case_proforma_preserves_product_commercial_info():
    print_case("CASO 4: proforma conserva precio y disponibilidad")

    data = run_full_handoff_flow()

    handoff_quote = data["handoff_quote"]
    handoff_proforma = data["handoff_proforma"]

    show_handoff("HANDOFF COTIZACIÃ“N", handoff_quote)
    show_handoff("HANDOFF PROFORMA", handoff_proforma)

    assert_condition(
        handoff_quote.get("producto_precio") == "$475,114 COP",
        "La cotizaciÃ³n debe tener precio original.",
    )

    assert_condition(
        handoff_proforma.get("producto_precio") == "$475,114 COP",
        "La proforma debe conservar el precio original.",
    )

    assert_condition(
        normalize_text(handoff_quote.get("producto_disponibilidad")) == "disponible en bogota (6 und)",
        "La cotizaciÃ³n debe tener disponibilidad original.",
    )

    assert_condition(
        normalize_text(handoff_proforma.get("producto_disponibilidad")) == "disponible en bogota (6 und)",
        "La proforma debe conservar la disponibilidad original.",
    )

    assert_condition(
        handoff_proforma.get("producto_precio") != "Consultarnos",
        "La proforma no debe degradar el precio a Consultarnos.",
    )

    assert_condition(
        handoff_proforma.get("producto_disponibilidad") != "Consultar disponibilidad",
        "La proforma no debe degradar disponibilidad.",
    )

    clear_session(data["session_id"])


# ============================================================
# CASO 5
# Handoff con telÃ©fono del canal
# ============================================================

def run_case_channel_phone_quote_handoff():
    print_case("CASO 5: handoff con telÃ©fono del canal")

    r1 = process_message(
        "busco el 300203",
        canal="whatsapp",
        cliente_id="573001234567",
    )

    session_id = r1["session_id"]
    session = get_session(session_id) or {}
    handoff = session.get("commercial_handoff") or {}

    show_response("RESPUESTA PRODUCTO CON TELÃ‰FONO CANAL", r1)
    show_handoff("HANDOFF TELÃ‰FONO CANAL", handoff)

    assert_condition(
        session.get("channel_contact_phone") == "3001234567",
        "Debe extraer el telÃ©fono del canal.",
    )

    assert_condition(
        session.get("commercial_contact_source") == "channel_phone",
        "Debe marcar fuente de contacto como channel_phone.",
    )

    assert_condition(
        handoff.get("tipo") == "cotizacion",
        "Con telÃ©fono de canal debe crear handoff tipo cotizaciÃ³n.",
    )

    assert_condition(
        handoff.get("telefono") == "3001234567",
        "El handoff debe guardar el telÃ©fono del canal.",
    )

    assert_condition(
        handoff.get("contact_source") == "channel_phone",
        "El handoff debe marcar contact_source channel_phone.",
    )

    assert_condition(
        handoff.get("producto_precio") == "$475,114 COP",
        "El handoff con telÃ©fono del canal debe conservar precio original.",
    )

    assert_condition(
        normalize_text(handoff.get("producto_disponibilidad")) == "disponible en bogota (6 und)",
        "El handoff con telÃ©fono del canal debe conservar disponibilidad original.",
    )

    assert_condition(
        handoff.get("producto_precio") != "Consultarnos",
        "El handoff con telÃ©fono del canal no debe degradar precio.",
    )

    assert_condition(
        handoff.get("producto_disponibilidad") != "Consultar disponibilidad",
        "El handoff con telÃ©fono del canal no debe degradar disponibilidad.",
    )

    clear_session(session_id)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA COMMERCIAL HANDOFF FLOW TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_exact_product_starts_quote()
    run_case_quote_handoff()
    run_case_proforma_handoff()
    run_case_proforma_preserves_product_commercial_info()
    run_case_channel_phone_quote_handoff()

    print("\nFIN TEST COMMERCIAL HANDOFF FLOW âœ…")


if __name__ == "__main__":
    main()

