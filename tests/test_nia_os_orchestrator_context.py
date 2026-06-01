# ============================================================
# tests/test_nia_os_orchestrator_context.py
# ============================================================
# OBJETIVO:
# Validar que el orquestador conecta NIA OS como metadata
# operativa segura.
#
# Fase actual:
# mensaje -> intent -> build_nia_os_context -> metadata compacta
#
# Este test NO valida todavía:
# - retrieval documental completo;
# - inyección de todos los módulos al prompt final;
# - respuesta basada 100% en documentos.
#
# Valida lo que ya está integrado:
# - intent NIA OS;
# - módulos activos;
# - guardrails declarados por módulo;
# - política documental segura;
# - prioridad del catálogo real.
# ============================================================

from pathlib import Path
import os
import json

from orchestration.nia_orchestrator import process_message
from memory.conversation_memory import clear_session


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
    if not condition:
        raise AssertionError(message)


def show_json(label: str, data):
    print_section(label)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def get_nia_os_metadata(response: dict) -> dict:
    """
    Obtiene metadata NIA OS desde la respuesta del orquestador.
    """
    if not isinstance(response, dict):
        return {}

    value = response.get("nia_os")

    if isinstance(value, dict):
        return value

    return {}


def get_document_policy(response: dict) -> dict:
    """
    Obtiene metadata de política documental.
    """
    if not isinstance(response, dict):
        return {}

    value = response.get("document_policy")

    if isinstance(value, dict):
        return value

    return {}


# ============================================================
# CASO 1
# Producto por código debe activar módulos de producto/API
# ============================================================

def run_case_product_code_uses_nia_os_context():
    print_section("CASO 1: código de producto usa metadata NIA OS")

    response = process_message(
        "busco el 300203",
        canal="web",
        cliente_id="test_nia_os_context_001",
    )

    show_json("RESPUESTA PRODUCTO", response)

    nia_os = get_nia_os_metadata(response)
    document_policy = get_document_policy(response)

    assert_condition(
        nia_os,
        "La respuesta debe incluir metadata nia_os.",
    )

    assert_condition(
        nia_os.get("intent") == "consulta_producto_codigo",
        "Para código exacto debe mapear a intent NIA OS consulta_producto_codigo.",
    )

    module_ids = nia_os.get("module_ids") or []

    assert_condition(
        isinstance(module_ids, list),
        "nia_os.module_ids debe ser una lista.",
    )

    assert_condition(
        "module_motor_api_productos" in module_ids,
        "Para producto/código debe cargar module_motor_api_productos.",
    )

    assert_condition(
        "module_guardrails_no_inventar" in module_ids,
        "Debe cargar module_guardrails_no_inventar.",
    )

    assert_condition(
        "module_motor_comercial" in module_ids,
        "Debe cargar module_motor_comercial.",
    )

    assert_condition(
        document_policy,
        "La respuesta debe incluir document_policy.",
    )

    assert_condition(
        document_policy.get("prioritize_catalog") is True,
        "Para código de producto debe priorizar catálogo real.",
    )

    assert_condition(
        document_policy.get("use_document_context") is False,
        "Para código exacto no debe usar contexto documental como fuente principal.",
    )

    assert_condition(
        response.get("exact_code") == "300203",
        "Debe conservar exact_code 300203.",
    )

    assert_condition(
        response.get("decision_reason") == "exact_code_detected_inside_message",
        "Debe conservar razón de decisión de código exacto.",
    )

    clear_session(response.get("session_id"))


# ============================================================
# CASO 2
# Saludo debe cargar metadata NIA OS sin romper respuesta simple
# ============================================================

def run_case_greeting_uses_nia_os_context():
    print_section("CASO 2: saludo usa metadata NIA OS")

    response = process_message(
        "hola",
        canal="web",
        cliente_id="test_nia_os_context_002",
    )

    show_json("RESPUESTA SALUDO", response)

    nia_os = get_nia_os_metadata(response)
    document_policy = get_document_policy(response)

    assert_condition(
        nia_os,
        "La respuesta de saludo debe incluir metadata nia_os.",
    )

    assert_condition(
        nia_os.get("intent") == "saludo",
        "Debe mapear saludo a intent NIA OS saludo.",
    )

    assert_condition(
        isinstance(nia_os.get("module_ids"), list),
        "Debe exponer module_ids.",
    )

    assert_condition(
        document_policy,
        "La respuesta de saludo debe incluir document_policy.",
    )

    assert_condition(
        document_policy.get("prioritize_catalog") in [True, False],
        "document_policy debe exponer prioritize_catalog como booleano.",
    )

    clear_session(response.get("session_id"))


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("NIA OS ORCHESTRATOR CONTEXT TEST")
    print("=" * 70)

    load_local_env()

    print("MONGO CARGADO:", bool(os.getenv("MONGO_CONNECTION_STRING")))

    run_case_product_code_uses_nia_os_context()
    run_case_greeting_uses_nia_os_context()

    print("\nFIN TEST NIA OS ORCHESTRATOR CONTEXT ✅")


if __name__ == "__main__":
    main()