# ============================================================
# tests/test_bitrix_client_disabled.py
# ============================================================
# OBJETIVO:
# Validar que el cliente Bitrix queda preparado pero seguro.
#
# En esta fase:
# - NO debe enviar nada a Bitrix.
# - Debe funcionar sin webhook.
# - Debe devolver preview/payload seguro.
# - Debe bloquear envío si BITRIX_ENABLED=false o falta config.
# ============================================================

import json
import os

from integrations.bitrix_client import (
    get_bitrix_config,
    build_bitrix_task_preview_from_opportunity,
    create_bitrix_task_from_opportunity,
)


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


def sample_opportunity():
    """
    Oportunidad comercial mínima similar al commercial_handoff real.
    """
    return {
        "handoff_id": "cotizacion_test_bitrix_client_001",
        "tipo": "cotizacion",
        "estado": "lista_para_asesor",
        "siguiente_paso": "generar_o_enviar_cotizacion",
        "created_at": "2026-06-02T14:00:00+00:00",
        "session_id": "test_session_bitrix_client_001",
        "canal": "web",
        "cliente_id": "test_cliente_bitrix_client_001",
        "contact_source": "manual",
        "producto_codigo": "300203",
        "producto_nombre": "Anemometros digitales portatiles Indicadores",
        "producto_marca": "lutron",
        "producto_referencia": "LM-81AM",
        "producto_precio": "$480,393 COP",
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
        "opportunity_id": "cotizacion_test_bitrix_client_001",
        "opportunity_saved": True,
        "schema_version": "commercial_opportunity_v1",
    }


def clear_bitrix_env():
    """
    Limpia variables Bitrix para pruebas controladas.
    """
    for key in [
        "BITRIX_ENABLED",
        "BITRIX_WEBHOOK_URL",
        "BITRIX_RESPONSIBLE_ID",
    ]:
        os.environ.pop(key, None)


def run_case_default_config_is_disabled():
    print_section("CASO 1: configuración por defecto está deshabilitada")

    clear_bitrix_env()

    config = get_bitrix_config()

    show_json("BITRIX CONFIG DEFAULT", config)

    assert_condition(
        config.get("enabled") is False,
        "Bitrix debe estar deshabilitado por defecto.",
    )

    assert_condition(
        config.get("ready_to_send") is False,
        "No debe estar listo para enviar sin configuración.",
    )

    assert_condition(
        "BITRIX_WEBHOOK_URL" in config.get("missing", []),
        "Debe faltar BITRIX_WEBHOOK_URL.",
    )

    assert_condition(
        "BITRIX_RESPONSIBLE_ID" in config.get("missing", []),
        "Debe faltar BITRIX_RESPONSIBLE_ID.",
    )


def run_case_preview_without_config():
    print_section("CASO 2: preview funciona sin configuración Bitrix")

    clear_bitrix_env()

    result = build_bitrix_task_preview_from_opportunity(sample_opportunity())

    show_json("BITRIX PREVIEW CLIENT", result)

    assert_condition(
        result.get("ok") is True,
        "Preview debe generarse correctamente.",
    )

    assert_condition(
        result.get("mode") == "preview",
        "Debe indicar modo preview.",
    )

    assert_condition(
        result.get("bitrix_enabled") is False,
        "Bitrix debe estar deshabilitado.",
    )

    assert_condition(
        result.get("ready_to_send") is False,
        "No debe estar listo para enviar.",
    )

    preview = result.get("preview") or {}

    assert_condition(
        preview.get("target") == "bitrix",
        "Preview debe apuntar a Bitrix.",
    )

    assert_condition(
        preview.get("method") == "tasks.task.add",
        "Preview debe usar método tasks.task.add.",
    )


def run_case_create_task_does_not_send_when_disabled():
    print_section("CASO 3: no envía si Bitrix está deshabilitado")

    clear_bitrix_env()

    os.environ["BITRIX_ENABLED"] = "false"
    os.environ["BITRIX_WEBHOOK_URL"] = "https://example.bitrix24.com/rest/fake/"
    os.environ["BITRIX_RESPONSIBLE_ID"] = "123"

    result = create_bitrix_task_from_opportunity(
        sample_opportunity(),
        dry_run=False,
    )

    show_json("BITRIX CREATE DISABLED RESULT", result)

    assert_condition(
        result.get("sent") is False,
        "No debe enviar si BITRIX_ENABLED=false.",
    )

    assert_condition(
        "bitrix_disabled" in result.get("blocked_reasons", []),
        "Debe bloquear por bitrix_disabled.",
    )

    assert_condition(
        result.get("ready_to_send") is False,
        "No debe estar listo si Bitrix está deshabilitado.",
    )


def run_case_create_task_does_not_send_with_missing_config():
    print_section("CASO 4: no envía si falta configuración")

    clear_bitrix_env()

    os.environ["BITRIX_ENABLED"] = "true"

    result = create_bitrix_task_from_opportunity(
        sample_opportunity(),
        dry_run=False,
    )

    show_json("BITRIX CREATE MISSING CONFIG RESULT", result)

    assert_condition(
        result.get("sent") is False,
        "No debe enviar si falta configuración.",
    )

    assert_condition(
        "missing_config" in result.get("blocked_reasons", []),
        "Debe bloquear por missing_config.",
    )

    assert_condition(
        "BITRIX_WEBHOOK_URL" in result.get("missing_config", []),
        "Debe reportar falta de BITRIX_WEBHOOK_URL.",
    )

    assert_condition(
        "BITRIX_RESPONSIBLE_ID" in result.get("missing_config", []),
        "Debe reportar falta de BITRIX_RESPONSIBLE_ID.",
    )


def run_case_dry_run_blocks_even_when_ready():
    print_section("CASO 5: dry_run bloquea aunque configuración esté completa")

    clear_bitrix_env()

    os.environ["BITRIX_ENABLED"] = "true"
    os.environ["BITRIX_WEBHOOK_URL"] = "https://example.bitrix24.com/rest/fake/"
    os.environ["BITRIX_RESPONSIBLE_ID"] = "123"

    result = create_bitrix_task_from_opportunity(
        sample_opportunity(),
        dry_run=True,
    )

    show_json("BITRIX CREATE DRY RUN RESULT", result)

    assert_condition(
        result.get("sent") is False,
        "No debe enviar en dry_run.",
    )

    assert_condition(
        result.get("ready_to_send") is True,
        "Debe estar listo técnicamente si la configuración está completa.",
    )

    assert_condition(
        "dry_run_enabled" in result.get("blocked_reasons", []),
        "Debe bloquear por dry_run_enabled.",
    )

    payload = result.get("payload") or {}

    assert_condition(
        payload.get("ready_to_send") is True,
        "El payload mapper debe quedar listo.",
    )


def main():
    print("=" * 70)
    print("NIA BITRIX CLIENT DISABLED TEST")
    print("=" * 70)

    run_case_default_config_is_disabled()
    run_case_preview_without_config()
    run_case_create_task_does_not_send_when_disabled()
    run_case_create_task_does_not_send_with_missing_config()
    run_case_dry_run_blocks_even_when_ready()

    print("\nFIN TEST BITRIX CLIENT DISABLED ✅")


if __name__ == "__main__":
    main()