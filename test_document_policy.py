# ============================================================
# test_document_policy.py
# ============================================================
# Prueba aislada de la política documental de NIA.
#
# Este test valida que NIA sepa cuándo:
# - usar contexto documental
# - priorizar catálogo real
# - evitar documentos para búsquedas de producto
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
    },
    {
        "name": "Código exacto",
        "message": "busco el producto P382280",
        "expected_document": False,
        "expected_catalog": True,
    },
    {
        "name": "Precio producto",
        "message": "precio de la válvula de bola",
        "expected_document": False,
        "expected_catalog": True,
    },
    {
        "name": "Consulta PLC técnica",
        "message": "necesito un plc con modbus y 16 entradas",
        "expected_document": False,
        "expected_catalog": True,
    },
    {
        "name": "Reglas no inventar",
        "message": "qué reglas tiene NIA para no inventar productos",
        "expected_document": True,
        "expected_catalog": True,
    },
    {
        "name": "Módulo guardrails",
        "message": "explícame module_guardrails_no_inventar",
        "expected_document": True,
        "expected_catalog": False,
    },
    {
        "name": "Visión archivos",
        "message": "qué hace module_vision_archivos",
        "expected_document": True,
        "expected_catalog": False,
    },
    {
        "name": "Documento explícito",
        "message": "revisa este manual técnico",
        "expected_document": True,
        "expected_catalog": False,
    },
    {
        "name": "Ficha técnica",
        "message": "qué dice la ficha tecnica del variador",
        "expected_document": True,
        "expected_catalog": True,
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
    Ejecuta pruebas de política documental.
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

        ok = document_ok and catalog_ok

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
            },
            "actual": {
                "use_document_context": result.get("use_document_context"),
                "prioritize_catalog": result.get("prioritize_catalog"),
                "source_type": result.get("source_type"),
                "confidence": result.get("confidence"),
                "reason": result.get("reason"),
            },
        })

    print_json("RESULTADOS", {
        "passed": passed,
        "failed": failed,
        "total": len(TEST_CASES),
        "results": results,
    })

    if failed == 0:
        print("\nFIN TEST DOCUMENT POLICY ✅")
    else:
        print("\nFIN TEST DOCUMENT POLICY CON ERRORES ❌")


if __name__ == "__main__":
    main()