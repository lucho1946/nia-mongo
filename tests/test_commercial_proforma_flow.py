# ============================================================
# test_commercial_proforma_flow.py
# ============================================================
# OBJETIVO:
# Validar el flujo comercial de proforma/cierre de NIA.
#
# Este test asegura que:
# 1. NIA no reinicie la cotizaciÃ³n cuando el cliente quiere comprar.
# 2. NIA avance a proforma cuando el cliente acepta o pide comprar.
# 3. NIA pida RUT, NIT o documento fiscal.
# 4. NIA capture NIT/RUT/documento fiscal.
# 5. NIA deje la proforma lista para revisiÃ³n del asesor.
#
# AlineaciÃ³n con Don AndrÃ©s:
# - Si el cliente quiere comprar, avanzar a proforma sin volver a vender desde cero.
# - Para proforma es obligatorio pedir RUT, NIT o documento fiscal.
# - No inventar datos.
# - No buscar productos nuevos cuando ya hay producto/cotizaciÃ³n activa.
# ============================================================

from pathlib import Path
import os


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


def assert_condition(condition: bool, message: str):
    """
    Assertion con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def run_base_quote_flow():
    """
    Crea una sesiÃ³n con:
    - producto 300203 seleccionado
    - cotizaciÃ³n iniciada
    - datos comerciales completos
    - seguimiento de cotizaciÃ³n enviada

    Retorna:
    - session_id
    - respuestas del flujo base
    """
    r1 = process_message("busco el 300203")
    session_id = r1["session_id"]

    r2 = process_message(
        "quiero cotizar este producto",
        session_id=session_id,
    )

    r3 = process_message(
        "Luis Diaz, ViaIndustrial. luis2004diazalzate@gmail.com",
        session_id=session_id,
    )

    r4 = process_message(
        "Ya me enviaron la cotizaciÃ³n",
        session_id=session_id,
    )

    return session_id, r1, r2, r3, r4


def show_response(label: str, response: dict):
    print_section(label)
    print("session_id:", response.get("session_id"))
    print("estado:", response.get("estado_negociacion") or response.get("estado"))
    print("respuesta:")
    print(response_text(response))


def show_session(session_id: str):
    session = get_session(session_id) or {}

    print("\n" + "-" * 70)
    print("SESSION FINAL")
    print("-" * 70)
    print("estado_negociacion:", session.get("estado_negociacion"))
    print("commercial_process_state:", session.get("commercial_process_state"))
    print("ultimo_paso:", session.get("ultimo_paso"))
    print("siguiente_paso:", session.get("siguiente_paso"))
    print("datos_faltantes:", session.get("datos_faltantes"))
    print("datos_faltantes_proforma:", session.get("datos_faltantes_proforma"))
    print("commercial_data:", session.get("commercial_data"))
    print("last_selected_product_code:", session.get("last_selected_product_code"))

    return session


# ============================================================
# CASO 1
# CotizaciÃ³n completa -> quiero comprar -> pide documento fiscal
# ============================================================

def run_flow_buy_intent_requests_fiscal_document():
    print_case("CASO 1: quiero comprar pide RUT/NIT/documento fiscal")

    session_id, r1, r2, r3, r4 = run_base_quote_flow()

    r5 = process_message(
        "quiero comprar",
        session_id=session_id,
    )

    show_response("RESPUESTA QUIERO COMPRAR", r5)

    session = show_session(session_id)

    assert_condition(
        "RUT, NIT o documento fiscal" in response_text(r5),
        "NIA debe pedir RUT, NIT o documento fiscal cuando el cliente quiere comprar.",
    )

    assert_condition(
        session.get("estado_negociacion") == "proforma_en_proceso",
        "El estado debe quedar en proforma_en_proceso.",
    )

    assert_condition(
        session.get("commercial_process_state") == "pedir_datos_faltantes_proforma",
        "El commercial_process_state debe quedar en pedir_datos_faltantes_proforma.",
    )

    assert_condition(
        session.get("datos_faltantes_proforma") == ["RUT, NIT o documento fiscal"],
        "Debe faltar Ãºnicamente RUT, NIT o documento fiscal.",
    )

    assert_condition(
        session.get("last_selected_product_code") == "300203",
        "Debe conservar el producto activo 300203.",
    )

    clear_session(session_id)


# ============================================================
# CASO 2
# Cliente entrega NIT -> proforma lista para asesor
# ============================================================

def run_flow_nit_capture_completes_proforma():
    print_case("CASO 2: captura NIT y deja proforma lista")

    session_id, r1, r2, r3, r4 = run_base_quote_flow()

    r5 = process_message(
        "quiero comprar",
        session_id=session_id,
    )

    r6 = process_message(
        "Mi NIT es 900123456-7",
        session_id=session_id,
    )

    show_response("RESPUESTA NIT", r6)

    session = show_session(session_id)
    commercial_data = session.get("commercial_data") or {}

    assert_condition(
        "documento fiscal" in response_text(r6).lower(),
        "La respuesta debe confirmar que recibiÃ³ el documento fiscal.",
    )

    assert_condition(
        session.get("estado_negociacion") == "datos_proforma_recibidos",
        "El estado debe quedar en datos_proforma_recibidos.",
    )

    assert_condition(
        session.get("commercial_process_state") == "proforma_lista_para_asesor",
        "El commercial_process_state debe quedar en proforma_lista_para_asesor.",
    )

    assert_condition(
        session.get("datos_faltantes_proforma") == [],
        "No deben quedar datos faltantes de proforma.",
    )

    assert_condition(
        commercial_data.get("documento_fiscal") == "900123456-7",
        "Debe guardar documento_fiscal con el NIT entregado.",
    )

    assert_condition(
        commercial_data.get("nit") == "900123456-7",
        "Debe guardar nit cuando el usuario dice NIT.",
    )

    clear_session(session_id)


# ============================================================
# CASO 3
# Cliente entrega RUT -> guarda rut y documento_fiscal
# ============================================================

def run_flow_rut_capture():
    print_case("CASO 3: captura RUT")

    session_id, r1, r2, r3, r4 = run_base_quote_flow()

    process_message(
        "hagamos la proforma",
        session_id=session_id,
    )

    r6 = process_message(
        "RUT 901234567",
        session_id=session_id,
    )

    show_response("RESPUESTA RUT", r6)

    session = show_session(session_id)
    commercial_data = session.get("commercial_data") or {}

    assert_condition(
        session.get("estado_negociacion") == "datos_proforma_recibidos",
        "Con RUT debe quedar en datos_proforma_recibidos.",
    )

    assert_condition(
        session.get("commercial_process_state") == "proforma_lista_para_asesor",
        "Con RUT debe quedar en proforma_lista_para_asesor.",
    )

    assert_condition(
        commercial_data.get("documento_fiscal") == "901234567",
        "Debe guardar documento_fiscal con el RUT entregado.",
    )

    assert_condition(
        commercial_data.get("rut") == "901234567",
        "Debe guardar rut cuando el usuario dice RUT.",
    )

    clear_session(session_id)


# ============================================================
# CASO 4
# Cliente responde solo nÃºmero fiscal
# ============================================================

def run_flow_plain_fiscal_number_capture():
    print_case("CASO 4: captura nÃºmero fiscal sin etiqueta")

    session_id, r1, r2, r3, r4 = run_base_quote_flow()

    process_message(
        "quiero pagar",
        session_id=session_id,
    )

    r6 = process_message(
        "900987654-1",
        session_id=session_id,
    )

    show_response("RESPUESTA DOCUMENTO SIN ETIQUETA", r6)

    session = show_session(session_id)
    commercial_data = session.get("commercial_data") or {}

    assert_condition(
        session.get("estado_negociacion") == "datos_proforma_recibidos",
        "Con documento fiscal sin etiqueta debe completar proforma.",
    )

    assert_condition(
        commercial_data.get("documento_fiscal") == "900987654-1",
        "Debe guardar documento_fiscal aunque el usuario no diga NIT/RUT.",
    )

    assert_condition(
        not commercial_data.get("nit"),
        "No debe guardar nit si el usuario no dijo NIT.",
    )

    assert_condition(
        not commercial_data.get("rut"),
        "No debe guardar rut si el usuario no dijo RUT.",
    )

    clear_session(session_id)


# ============================================================
# CASO 5
# Varias frases de intenciÃ³n deben activar proforma
# ============================================================

def run_flow_multiple_proforma_intent_phrases():
    print_case("CASO 5: frases naturales activan proforma")

    phrases = [
        "apruebo la cotizaciÃ³n",
        "sigamos",
        "procedamos",
        "quiero pagar",
        "envÃ­ame la proforma",
        "necesito la proforma",
    ]

    for phrase in phrases:
        session_id, r1, r2, r3, r4 = run_base_quote_flow()

        r5 = process_message(
            phrase,
            session_id=session_id,
        )

        show_response(f"RESPUESTA FRASE: {phrase}", r5)

        session = get_session(session_id) or {}

        assert_condition(
            session.get("estado_negociacion") == "proforma_en_proceso",
            f"La frase '{phrase}' debe activar proforma_en_proceso.",
        )

        assert_condition(
            session.get("commercial_process_state") == "pedir_datos_faltantes_proforma",
            f"La frase '{phrase}' debe pedir datos faltantes de proforma.",
        )

        assert_condition(
            "RUT, NIT o documento fiscal" in response_text(r5),
            f"La frase '{phrase}' debe provocar solicitud de RUT/NIT/documento fiscal.",
        )

        clear_session(session_id)


# ============================================================
# CASO 6
# Sin contexto comercial, no debe activar proforma
# ============================================================

def run_flow_no_commercial_context_does_not_force_proforma():
    print_case("CASO 6: sin contexto comercial no fuerza proforma")

    r1 = process_message("quiero comprar")
    session_id = r1["session_id"]

    show_response("RESPUESTA SIN CONTEXTO", r1)

    session = show_session(session_id)

    assert_condition(
        session.get("commercial_process_state") != "pedir_datos_faltantes_proforma",
        "Sin producto/cotizaciÃ³n previa no debe entrar a pedir datos de proforma.",
    )

    assert_condition(
        session.get("estado_negociacion") != "proforma_en_proceso",
        "Sin contexto comercial no debe quedar en proforma_en_proceso.",
    )

    clear_session(session_id)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA COMMERCIAL PROFORMA FLOW TEST")
    print("=" * 70)

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_flow_buy_intent_requests_fiscal_document()
    run_flow_nit_capture_completes_proforma()
    run_flow_rut_capture()
    run_flow_plain_fiscal_number_capture()
    run_flow_multiple_proforma_intent_phrases()
    run_flow_no_commercial_context_does_not_force_proforma()

    print("\nFIN TEST COMMERCIAL PROFORMA FLOW âœ…")


if __name__ == "__main__":
    main() 

