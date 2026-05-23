# ============================================================
# test_brain.py
# ============================================================
# Prueba conversacional limpia del cerebro de NIA.
#
# Este test valida:
# - memoria conversacional
# - intención
# - preguntas técnicas
# - búsqueda por catálogo
# - compatibilidad de resultados
# - respuesta final
#
# Ya NO imprime DEBUG interno.
# Si luego necesitamos diagnosticar, podemos volver a activar
# context, decision_reason, compatible_count y priority_fields.
# ============================================================

from dotenv import load_dotenv

# Cargar variables de entorno antes de importar el orquestador.
# Esto es importante para que MongoDB y otros servicios estén disponibles.
load_dotenv()

from orchestration.nia_orchestrator import process_message


# ============================================================
# ESCENARIOS DE PRUEBA
# ============================================================

SCENARIOS = [
    {
        "title": "ESCENARIO 1 - Sensor de presión",
        "messages": [
            "necesito un sensor",
            "presion",
            "0-10 bar",
        ],
    },
    {
        "title": "ESCENARIO 2 - Motor Siemens",
        "messages": [
            "motor siemens",
            "5hp",
            "220v",
        ],
    },
    {
        "title": "ESCENARIO 3 - PLC",
        "messages": [
            "necesito un plc",
            "16 entradas",
            "modbus",
        ],
    },
    {
        "title": "ESCENARIO 4 - Variador",
        "messages": [
            "precio variador",
            "3hp",
            "220v",
        ],
    },
    {
        "title": "ESCENARIO 5 - Código exacto",
        "messages": [
            "P382280",
        ],
    },
    {
        "title": "ESCENARIO 6 - Torquímetro",
        "messages": [
            "necesito un torquimetro",
            "200nm",
        ],
    },
]


# ============================================================
# UTILIDADES DE IMPRESIÓN
# ============================================================

def print_separator():
    print("\n" + "-" * 60)


def print_products(result: dict):
    """
    Imprime productos encontrados si existen.
    """

    cards = result.get("cards") or []

    if not cards:
        return

    print("\nPRODUCTOS:")

    for product in cards:
        codigo = product.get("codigo", "Sin código")
        nombre = product.get("nombre", "Sin nombre")
        marca = product.get("marca", "Sin marca")

        print(f"- {codigo} | {nombre} | {marca}")


def print_response(user_message: str, result: dict):
    """
    Imprime mensaje del usuario y respuesta de NIA.
    """

    print(f"\n👤 USER: {user_message}")
    print("\n🤖 NIA:")
    print(result.get("response", "Sin respuesta"))

    print_products(result)

    if result.get("needs_clarification"):
        print("\n[modo aclaración]")


# ============================================================
# EJECUCIÓN DE TEST
# ============================================================

def run_tests():
    print("\n" + "=" * 60)
    print("NIA CONVERSATIONAL BRAIN TEST")
    print("=" * 60)

    for scenario in SCENARIOS:
        print_separator()
        print(scenario["title"])
        print_separator()

        session_id = None

        for message in scenario["messages"]:
            result = process_message(
                message=message,
                session_id=session_id,
            )

            # Mantener la misma sesión dentro del escenario.
            session_id = result.get("session_id")

            print_response(message, result)

    print("\n" + "=" * 60)
    print("FIN TEST")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()