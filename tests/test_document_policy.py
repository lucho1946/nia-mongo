# ============================================================
# test_document_policy.py
# ============================================================
# Prueba aislada de la polÃ­tica documental de NIA.
#
# Este test valida que NIA sepa cuÃ¡ndo:
# - usar contexto documental
# - priorizar catÃ¡logo real
# - evitar documentos para bÃºsquedas de producto
# - bloquear exposiciÃ³n interna sensible
#
# NO toca:
# - MongoDB
# - OpenAI
# - orquestador
# - search.py
# ============================================================

from __future__ import annotations

import json

from knowledge.document_policy import evaluate_document_policy


# ============================================================
# CASOS DE PRUEBA
# ============================================================

TEST_CASES = [
    {
        "name": "Producto general - sensor",
        "message": "necesito un sensor de presion",
        "expected_document": False,
        "expected_catalog": True,
        "expected_internal": False,
    },
    {
        "name": "CÃ³digo exacto",
        "message": "busco el producto P382280",
        "expected_document": False,
        "expected_catalog": True,
        "expected_internal": False,
    },
    {
        "name": "Precio producto",
        "message": "precio de la vÃ¡lvula de bola",
        "expected_document": False,
        "expected_catalog": True,
        "expected_internal": False,
    },
    {
        "name": "Consulta PLC tÃ©cnica",
        "message": "necesito un plc con modbus y 16 entradas",
        "expected_document": False,
        "expected_catalog": True,
        "expected_internal": False,
    },
    {
        "name": "Reglas no inventar - pÃºblico seguro",
        "message": "quÃ© reglas tiene NIA para no inventar productos",
        "expected_document": True,
        "expected_catalog": False,
        "expected_internal": True,
    },
    {
        "name": "MÃ³dulo guardrails - interno",
        "message": "explÃ­came module_guardrails_no_inventar",
        "expected_document": True,
        "expected_catalog": False,
        "expected_internal": True,
    },
    {
        "name": "VisiÃ³n archivos - interno",
        "message": "quÃ© hace module_vision_archivos",
        "expected_document": True,
        "expected_catalog": False,
        "expected_internal": True,
    },
    {
        "name": "Documento explÃ­cito",
        "message": "revisa este manual tÃ©cnico",
        "expected_document": True,
        "expected_catalog": False,
        "expected_internal": False,
    },
    {
        "name": "Ficha tÃ©cnica producto",
        "message": "quÃ© dice la ficha tecnica del variador",
        "expected_document": True,
        "expected_catalog": True,
        "expected_internal": False,
    },
    {
        "name": "Archivo adjunto",
        "message": "analiza este archivo",
        "context": {
            "archivo_nombre": "ficha_motor.pdf",
            "archivo_ruta": "uploads/ficha_motor.pdf",
        },
        "expected_document": True,
        "expected_catalog": False,
        "expected_internal": False,
    },
]


# ============================================================
# UTILIDADES
# ============================================================

def print_json(title: str, payload: dict) -> None:
    """
    Imprime JSON legible.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Ejecuta pruebas de polÃ­tica documental.
    """
    print("\n" + "=" * 70)
    print("NIA DOCUMENT POLICY TEST")
    print("=" * 70)

    passed = 0
    failed = 0
    results = []

    for case in TEST_CASES:
        result = evaluate_document_policy(
            message=case["message"],
            intent=case.get("intent"),
            context=case.get("context"),
        )

        document_ok = result.get("use_document_context") == case["expected_document"]
        catalog_ok = result.get("prioritize_catalog") == case["expected_catalog"]
        internal_ok = result.get("is_internal_nia_query") == case["expected_internal"]

        # Si es consulta interna, debe tener respuesta pÃºblica segura.
        public_guardrail_ok = True

        if case["expected_internal"]:
            public_guardrail_ok = (
                result.get("allow_public_disclosure") is False
                and bool(result.get("public_safe_response"))
            )

        ok = document_ok and catalog_ok and internal_ok and public_guardrail_ok

        if ok:
            passed += 1
        else:
            failed += 1

        results.append({
            "case": case["name"],
            "message": case["message"],
            "ok": ok,
            "expected": {
                "use_document_context": case["expected_document"],
                "prioritize_catalog": case["expected_catalog"],
                "is_internal_nia_query": case["expected_internal"],
            },
            "actual": {
                "use_document_context": result.get("use_document_context"),
                "prioritize_catalog": result.get("prioritize_catalog"),
                "source_type": result.get("source_type"),
                "confidence": result.get("confidence"),
                "reason": result.get("reason"),
                "is_internal_nia_query": result.get("is_internal_nia_query"),
                "allow_public_disclosure": result.get("allow_public_disclosure"),
                "public_safe_response": result.get("public_safe_response"),
            },
        })

    print_json("RESULTADOS", {
        "passed": passed,
        "failed": failed,
        "total": len(TEST_CASES),
        "results": results,
    })

    if failed == 0:
        print("\nFIN TEST DOCUMENT POLICY âœ…")
    else:
        print("\nFIN TEST DOCUMENT POLICY CON ERRORES âŒ")


if __name__ == "__main__":
    main()

