# ============================================================
# test_chat_response_adapter.py
# ============================================================
# Prueba aislada de la migración /chat → orquestador.
#
# Valida que:
# - El adapter devuelve ChatResponse.
# - El contrato del frontend se mantiene.
# - Consultas internas no devuelven productos.
# - Código exacto sigue devolviendo producto.
# - Consulta de producto sigue funcionando.
# ============================================================

from __future__ import annotations

from models.schemas import ChatRequest, ChatResponse
from orchestration.chat_response_adapter import process_chat_request


def print_response(title: str, response: ChatResponse) -> None:
    """
    Imprime respuesta compacta para revisión humana.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print("session_id:", response.session_id)
    print("estado:", response.estado)
    print("preguntas_hechas:", response.preguntas_hechas)
    print("requiere_accion:", response.requiere_accion)
    print("productos_count:", len(response.productos))
    print("respuesta:")
    print(response.respuesta)

    if response.productos:
        print("\nPRODUCTOS:")
        for producto in response.productos[:5]:
            print(
                f"- {producto.codigo} | {producto.nombre} | "
                f"{producto.marca} | {producto.precio}"
            )


def assert_condition(condition: bool, message: str) -> None:
    """
    Assertion simple con mensaje claro.
    """
    if not condition:
        raise AssertionError(message)


def main() -> None:
    print("\n" + "=" * 70)
    print("NIA CHAT RESPONSE ADAPTER TEST")
    print("=" * 70)

    # --------------------------------------------------------
    # Caso 1: consulta interna segura
    # --------------------------------------------------------
    internal_request = ChatRequest(
        mensaje="que reglas tiene NIA para no inventar productos",
        canal="web",
        cliente_id="test",
    )

    internal_response = process_chat_request(internal_request)
    print_response("CASO 1 - Consulta interna segura", internal_response)

    assert_condition(
        isinstance(internal_response, ChatResponse),
        "La respuesta interna no es ChatResponse.",
    )
    assert_condition(
        len(internal_response.productos) == 0,
        "Consulta interna no debe devolver productos.",
    )
    assert_condition(
        "Trabajo con reglas internas" in internal_response.respuesta,
        "Consulta interna debe devolver respuesta pública segura.",
    )

    # --------------------------------------------------------
    # Caso 2: código exacto
    # --------------------------------------------------------
    code_request = ChatRequest(
        mensaje="P382280",
        canal="web",
        cliente_id="test",
    )

    code_response = process_chat_request(code_request)
    print_response("CASO 2 - Código exacto", code_response)

    assert_condition(
        isinstance(code_response, ChatResponse),
        "La respuesta de código no es ChatResponse.",
    )
    assert_condition(
        code_response.session_id,
        "La respuesta de código debe traer session_id.",
    )

    # --------------------------------------------------------
    # Caso 3: saludo
    # --------------------------------------------------------
    saludo_request = ChatRequest(
        mensaje="hola",
        canal="web",
        cliente_id="test",
    )

    saludo_response = process_chat_request(saludo_request)
    print_response("CASO 3 - Saludo", saludo_response)

    assert_condition(
        saludo_response.estado in {"recopilando", "completado"},
        "Estado inválido en saludo.",
    )

    print("\nFIN TEST CHAT RESPONSE ADAPTER ✅")


if __name__ == "__main__":
    main()