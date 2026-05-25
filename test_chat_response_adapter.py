# ============================================================
# test_chat_response_adapter.py
# ============================================================
# Prueba aislada de la migración /chat → orquestador.
#
# Valida:
# - Adapter devuelve ChatResponse.
# - El contrato del frontend se mantiene.
# - Consultas internas no devuelven productos.
# - Código exacto funciona aunque venga dentro de frase.
# - La memoria anterior no contamina una búsqueda por código.
# - Saludos puros no disparan búsqueda técnica.
# - Consulta natural de variador se detecta correctamente.
# - Torquímetro + 200nm no se trata como código.
# - Continuidad comercial: "Envíame una cotización" usa último producto.
# ============================================================

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

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
    # Caso 2: código exacto puro
    # --------------------------------------------------------
    code_request = ChatRequest(
        mensaje="P382280",
        canal="web",
        cliente_id="test",
    )

    code_response = process_chat_request(code_request)
    print_response("CASO 2 - Código exacto puro", code_response)

    assert_condition(
        isinstance(code_response, ChatResponse),
        "La respuesta de código no es ChatResponse.",
    )
    assert_condition(
        len(code_response.productos) >= 1,
        "Código exacto P382280 debe devolver producto.",
    )
    assert_condition(
        code_response.productos[0].codigo.upper() == "P382280",
        "El producto devuelto debe ser P382280.",
    )

    # --------------------------------------------------------
    # Caso 3: saludo puro
    # --------------------------------------------------------
    saludo_request = ChatRequest(
        mensaje="hola buenas",
        canal="web",
        cliente_id="test",
    )

    saludo_response = process_chat_request(saludo_request)
    print_response("CASO 3 - Saludo puro", saludo_response)

    assert_condition(
        len(saludo_response.productos) == 0,
        "Un saludo puro no debe devolver productos.",
    )
    assert_condition(
        saludo_response.estado in {"recopilando", "completado"},
        "Estado inválido en saludo.",
    )

    # --------------------------------------------------------
    # Caso 4: consulta natural de variador
    # --------------------------------------------------------
    variador_request = ChatRequest(
        mensaje="me regalas el precio del variador 3hp 220v",
        session_id=None,
        canal="web",
        cliente_id="test_variador_limpio",
    )

    variador_response = process_chat_request(variador_request)
    print_response("CASO 4 - Variador natural", variador_response)

    assert_condition(
        isinstance(variador_response, ChatResponse),
        "La respuesta de variador no es ChatResponse.",
    )
    assert_condition(
        "cutter" not in variador_response.respuesta.lower(),
        "No debe recomendar cutter como variador.",
    )
    assert_condition(
        "display para variador" not in variador_response.respuesta.lower(),
        "No debe recomendar display como variador principal.",
    )
    assert_condition(
        all(producto.codigo.upper() != "P382280" for producto in variador_response.productos),
        "Variador natural no debe arrastrar P382280.",
    )

    # --------------------------------------------------------
    # Caso 5: memoria contaminada + código dentro de frase
    # --------------------------------------------------------
    primera = process_chat_request(
        ChatRequest(
            mensaje="precio variador 3hp 220v",
            canal="web",
            cliente_id="test",
        )
    )

    segunda = process_chat_request(
        ChatRequest(
            mensaje="busco el P382280",
            session_id=primera.session_id,
            canal="web",
            cliente_id="test",
        )
    )

    print_response("CASO 5 - Código dentro de frase limpia memoria", segunda)

    assert_condition(
        len(segunda.productos) >= 1,
        "Busco el P382280 debe devolver producto aunque antes hubiera contexto de variador.",
    )
    assert_condition(
        segunda.productos[0].codigo.upper() == "P382280",
        "La búsqueda por frase debe devolver P382280.",
    )

    # --------------------------------------------------------
    # Caso 6: torquímetro + medida no debe tratar 200nm como código
    # --------------------------------------------------------
    torquimetro_1 = process_chat_request(
        ChatRequest(
            mensaje="necesito un torquimetro",
            canal="web",
            cliente_id="test_torquimetro",
        )
    )

    torquimetro_2 = process_chat_request(
        ChatRequest(
            mensaje="200nm",
            session_id=torquimetro_1.session_id,
            canal="web",
            cliente_id="test_torquimetro",
        )
    )

    print_response("CASO 6 - Torquímetro con medida 200nm", torquimetro_2)

    assert_condition(
        "Encontré el código" not in torquimetro_2.respuesta,
        "200nm no debe tratarse como código de producto.",
    )
    assert_condition(
        all(producto.codigo.upper() != "P382280" for producto in torquimetro_2.productos),
        "Torquímetro 200nm no debe devolver P382280.",
    )

    # --------------------------------------------------------
    # Caso 7: continuidad comercial con último producto seleccionado
    # --------------------------------------------------------
    flujo_1 = process_chat_request(
        ChatRequest(
            mensaje="Hola",
            canal="web",
            cliente_id="test_cotizacion",
        )
    )

    flujo_2 = process_chat_request(
        ChatRequest(
            mensaje="necesito el producto 300230",
            session_id=flujo_1.session_id,
            canal="web",
            cliente_id="test_cotizacion",
        )
    )

    flujo_3 = process_chat_request(
        ChatRequest(
            mensaje="Perdon es el 300203",
            session_id=flujo_2.session_id,
            canal="web",
            cliente_id="test_cotizacion",
        )
    )

    flujo_4 = process_chat_request(
        ChatRequest(
            mensaje="Quiero cotizar: Anemometros digitales portatiles Indicadores (Código: 300203)",
            session_id=flujo_3.session_id,
            canal="web",
            cliente_id="test_cotizacion",
        )
    )

    flujo_5 = process_chat_request(
        ChatRequest(
            mensaje="Enviame una cotizacion",
            session_id=flujo_4.session_id,
            canal="web",
            cliente_id="test_cotizacion",
        )
    )

    print_response("CASO 7 - Continuidad comercial cotización", flujo_5)

    assert_condition(
        len(flujo_5.productos) >= 1,
        "La continuidad comercial debe devolver el último producto seleccionado.",
    )
    assert_condition(
        flujo_5.productos[0].codigo == "300203",
        "La cotización debe continuar con el producto 300203.",
    )
    assert_condition(
        "Medidor De Octanaje" not in flujo_5.respuesta,
        "No debe buscar productos nuevos por la frase cotización.",
    )
    assert_condition(
        "Detector de metales" not in flujo_5.respuesta,
        "No debe devolver detector de metales en continuidad de cotización.",
    )
    assert_condition(
        "Alcoholimetro" not in flujo_5.respuesta,
        "No debe devolver alcoholímetro en continuidad de cotización.",
    )
    assert_condition(
        "cotización" in flujo_5.respuesta.lower()
        or "cotizacion" in flujo_5.respuesta.lower(),
        "La respuesta debe hablar de cotización.",
    )

    print("\nFIN TEST CHAT RESPONSE ADAPTER ✅")


if __name__ == "__main__":
    main()