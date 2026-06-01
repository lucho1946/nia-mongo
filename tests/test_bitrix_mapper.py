# ============================================================
# tests/test_bitrix_mapper.py
# ============================================================
# OBJETIVO:
# Validar el mapper de oportunidades NIA hacia payload Bitrix.
#
# Este test NO envía datos a Bitrix.
# Solo valida que una oportunidad comercial generada por NIA
# se transforme en una tarea lista para enviar cuando exista webhook.
# ============================================================

import json

from integrations.bitrix_mapper import (
    map_opportunity_to_bitrix_task_payload,
    map_opportunity_to_bitrix_preview,
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


def build_sample_opportunity():
    """
    Oportunidad ejemplo basada en el flujo real de NIA.
    """
    return {
        "opportunity_id": "cotizacion_test_bitrix_mapper_001",
        "handoff_id": "cotizacion_test_bitrix_mapper_001",
        "tipo": "cotizacion",
        "estado": "lista_para_asesor",
        "siguiente_paso": "generar_o_enviar_cotizacion",
        "created_at": "2026-06-01T17:50:23.126298+00:00",
        "updated_at": "2026-06-01T17:50:23.126363+00:00",
        "session_id": "test_session_bitrix_mapper_001",
        "canal": "web",
        "cliente_id": "test_cliente_bitrix_mapper_001",
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
        "source": "nia_commercial_handoff",
        "schema_version": "commercial_opportunity_v1",
    }


def run_case_mapper_without_responsible_id():
    print_section("CASO 1: mapper sin responsible_id")

    opportunity = build_sample_opportunity()

    payload = map_opportunity_to_bitrix_task_payload(opportunity)

    show_json("BITRIX PAYLOAD", payload)

    assert_condition(payload.get("ok") is True, "Payload debe ser ok=True.")
    assert_condition(payload.get("target") == "bitrix", "Target debe ser bitrix.")
    assert_condition(payload.get("method") == "tasks.task.add", "Método debe ser tasks.task.add.")

    assert_condition(
        payload.get("ready_to_send") is False,
        "Sin responsible_id no debe estar listo para envío real.",
    )

    assert_condition(
        "responsible_id" in payload.get("missing", []),
        "Debe indicar que falta responsible_id.",
    )

    fields = payload.get("fields", {})

    assert_condition(
        fields.get("TITLE") == "Nueva cotización NIA - 300203 - Luis Diaz",
        "Título Bitrix incorrecto.",
    )

    description = fields.get("DESCRIPTION", "")

    expected_fragments = [
        "Oportunidad comercial generada por NIA",
        "Cliente: Luis Diaz",
        "Empresa: Viaindustrial",
        "Correo: luis2004diazalzate@gmail.com",
        "Código: 300203",
        "Precio: $480,393 COP",
        "Disponibilidad: Disponible en Bogotá (6 und)",
        "Opportunity ID: cotizacion_test_bitrix_mapper_001",
        "Session ID: test_session_bitrix_mapper_001",
    ]

    for fragment in expected_fragments:
        assert_condition(
            fragment in description,
            f"La descripción debe incluir: {fragment}",
        )

    tags = fields.get("TAGS", [])

    assert_condition("NIA" in tags, "Debe incluir tag NIA.")
    assert_condition("cotizacion" in tags, "Debe incluir tag cotizacion.")
    assert_condition("canal_web" in tags, "Debe incluir tag canal_web.")
    assert_condition("lista_para_asesor" in tags, "Debe incluir tag lista_para_asesor.")


def run_case_mapper_with_responsible_id():
    print_section("CASO 2: mapper con responsible_id")

    opportunity = build_sample_opportunity()

    payload = map_opportunity_to_bitrix_task_payload(
        opportunity,
        responsible_id=123,
    )

    show_json("BITRIX PAYLOAD READY", payload)

    fields = payload.get("fields", {})

    assert_condition(
        payload.get("ready_to_send") is True,
        "Con responsible_id debe estar listo para envío.",
    )

    assert_condition(
        payload.get("missing") == [],
        "No deben faltar campos si hay responsible_id.",
    )

    assert_condition(
        fields.get("RESPONSIBLE_ID") == 123,
        "Debe conservar RESPONSIBLE_ID.",
    )


def run_case_preview():
    print_section("CASO 3: preview Bitrix")

    opportunity = build_sample_opportunity()

    preview = map_opportunity_to_bitrix_preview(opportunity)

    show_json("BITRIX PREVIEW", preview)

    assert_condition(preview.get("ok") is True, "Preview debe ser ok=True.")
    assert_condition(preview.get("title"), "Preview debe tener title.")
    assert_condition(preview.get("description"), "Preview debe tener description.")
    assert_condition(preview.get("raw_payload"), "Preview debe incluir raw_payload.")


def main():
    print("=" * 70)
    print("NIA BITRIX MAPPER TEST")
    print("=" * 70)

    run_case_mapper_without_responsible_id()
    run_case_mapper_with_responsible_id()
    run_case_preview()

    print("\nFIN TEST BITRIX MAPPER ✅")


if __name__ == "__main__":
    main()