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
        mensaje="cual es el precio del variador 3hp 220v",
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
    
    # ============================================================
    # CASO 8 - Contexto activo: sensor fotoeléctrico
    # ============================================================
    # Objetivo:
    # Validar que NIA recuerde la última pregunta hecha.
    #
    # Flujo esperado:
    # Usuario: necesito un sensor industrial
    # NIA: pregunta subtipo
    # Usuario: sensor fotoelectrico
    # NIA: NO debe repetir "¿Qué tipo específico necesitas?"
    # ============================================================

    sensor_1 = process_chat_request(
        ChatRequest(
            mensaje="necesito un sensor industrial",
            canal="web",
            cliente_id="test_sensor_fotoelectrico",
        )
    )

    sensor_2 = process_chat_request(
        ChatRequest(
            mensaje="sensor fotoelectrico",
            session_id=sensor_1.session_id,
            canal="web",
            cliente_id="test_sensor_fotoelectrico",
        )
    )

    print_response("CASO 8 - Sensor fotoeléctrico responde subtipo pendiente", sensor_2)

    assert_condition(
        "¿Qué tipo específico necesitas?" not in sensor_2.respuesta,
        "NIA no debe repetir la pregunta de subtipo cuando el usuario responde sensor fotoelectrico.",
    )

    assert_condition(
    len(sensor_2.productos) >= 1,
    "NIA debe devolver productos o avanzar correctamente cuando el usuario responde sensor fotoelectrico.",
)

    assert_condition(
        any(
            "foto" in producto.nombre.lower()
        or "foto" in producto.descripcion.lower()
        or "foto" in producto.referencia.lower()
        for producto in sensor_2.productos
    ),
    "NIA debe devolver productos relacionados con sensor fotoelectrico.",
)

    # ============================================================
    # CASO 9 - Solicitud genérica no pregunta marca primero
    # ============================================================
    # Objetivo:
    # Validar que si el usuario solo dice "necesito un producto",
    # NIA pregunte qué producto busca o para qué aplicación,
    # en vez de preguntar marca.
    # ============================================================

    generico_1 = process_chat_request(
        ChatRequest(
            mensaje="necesito un producto",
            canal="web",
            cliente_id="test_producto_generico",
        )
    )

    print_response("CASO 9 - Producto genérico pregunta producto/aplicación", generico_1)

    assert_condition(
        "marca" not in generico_1.respuesta.lower(),
        "NIA no debe preguntar marca primero cuando el usuario solo dice necesito un producto.",
    )

    assert_condition(
        "producto" in generico_1.respuesta.lower()
        or "aplicación" in generico_1.respuesta.lower()
        or "aplicacion" in generico_1.respuesta.lower(),
        "NIA debe preguntar qué producto busca o para qué aplicación lo necesita.",
    )
    
        # ============================================================
    # CASO 10 - Cotización con código explícito desde lista
    # ============================================================
    # Objetivo:
    # Si NIA muestra varias opciones y el usuario elige una card
    # con código explícito, ese código debe mandar sobre el primer
    # producto recomendado.
    #
    # Bug corregido:
    # Antes el usuario elegía P256146, pero NIA cotizaba P101722.
    # ============================================================

    sensor_lista = process_chat_request(
        ChatRequest(
            mensaje="necesito un sensor fotoelectrico",
            canal="web",
            cliente_id="test_cotiza_sensor_codigo_explicito",
        )
    )

    sensor_cotizacion = process_chat_request(
        ChatRequest(
            mensaje=(
                "Quiero cotizar: Sensor fotoelectrico emisor receptor "
                "1 Metro 12-24vdc pnp (Código: P256146)"
            ),
            session_id=sensor_lista.session_id,
            canal="web",
            cliente_id="test_cotiza_sensor_codigo_explicito",
        )
    )

    print_response(
        "CASO 10 - Cotización usa código explícito P256146",
        sensor_cotizacion,
    )

    assert_condition(
        "P256146" not in sensor_cotizacion.respuesta,
        "La respuesta visible no debe mostrar el código del producto seleccionado.",
    )

    assert_condition(
        len(sensor_cotizacion.productos) >= 1,
        "NIA debe devolver el producto seleccionado para cotización.",
    )

    assert_condition(
        sensor_cotizacion.productos[0].codigo == "P256146",
        "El primer producto de la cotización debe ser P256146, no el primer resultado anterior.",
    )

    # ============================================================
    # CASO 11 - Código exacto conserva producto activo para cotización
    # ============================================================
    # Objetivo:
    # Si el usuario busca un código exacto y luego dice:
    # "quiero cotizar este producto", NIA debe usar ese producto.
    #
    # Bug corregido:
    # Antes NIA respondía: ¿Qué producto buscas?
    # porque la rama de código exacto no persistía la sesión.
    # ============================================================

    exacto_1 = process_chat_request(
        ChatRequest(
            mensaje="hola",
            canal="web",
            cliente_id="test_cotiza_300203",
        )
    )

    exacto_2 = process_chat_request(
        ChatRequest(
            mensaje="busco el producto 300203",
            session_id=exacto_1.session_id,
            canal="web",
            cliente_id="test_cotiza_300203",
        )
    )

    exacto_3 = process_chat_request(
        ChatRequest(
            mensaje="quiero cotizar este producto",
            session_id=exacto_2.session_id,
            canal="web",
            cliente_id="test_cotiza_300203",
        )
    )

    print_response(
        "CASO 11 - Código exacto conserva producto activo para cotización",
        exacto_3,
    )

    assert_condition(
        "300203" not in exacto_3.respuesta,
        "La respuesta visible no debe mostrar el código del producto seleccionado.",
    )
    
    assert_condition(
        len(exacto_3.productos) >= 1,
        "NIA debe devolver el producto activo 300203 en la cotización.",
    )

    assert_condition(
        exacto_3.productos[0].codigo == "300203",
        "El producto activo de la cotización debe ser 300203.",
    )
    
        # ============================================================
    # CASO 12 - Captura datos comerciales parciales
    # ============================================================
    # Objetivo:
    # Después de iniciar cotización, si el usuario entrega nombre,
    # empresa y correo, NIA debe guardar esos datos y NO volver
    # a pedirlos. Si falta contacto alterno no es obligatorio,
    # porque correo o teléfono son medio de contacto válido.
    # ============================================================

    cotizacion_base = process_chat_request(
        ChatRequest(
            mensaje="busco el producto 300203",
            canal="web",
            cliente_id="test_datos_comerciales",
        )
    )

    cotizacion_inicio = process_chat_request(
        ChatRequest(
            mensaje="quiero cotizar este producto",
            session_id=cotizacion_base.session_id,
            canal="web",
            cliente_id="test_datos_comerciales",
        )
    )

    datos_cliente = process_chat_request(
        ChatRequest(
            mensaje="Soy Carlos de Industrias ABC, mi correo es carlos@abc.com",
            session_id=cotizacion_inicio.session_id,
            canal="web",
            cliente_id="test_datos_comerciales",
        )
    )

    print_response(
        "CASO 12 - Captura datos comerciales para cotización",
        datos_cliente,
    )

    assert_condition(
        "Carlos" in datos_cliente.respuesta,
        "NIA debe reconocer el nombre del cliente cuando viene en el mensaje.",
    )

    assert_condition(
        "correo" in datos_cliente.respuesta.lower(),
        "NIA debe confirmar que recibió el correo o los datos comerciales.",
    )

    assert_condition(
        len(datos_cliente.productos) >= 1,
        "NIA debe conservar el producto seleccionado durante la captura comercial.",
    )

    assert_condition(
        datos_cliente.productos[0].codigo == "300203",
        "NIA debe mantener el producto activo 300203 durante la captura de datos.",
    )

    # ============================================================
    # CASO 13 - Datos comerciales incompletos
    # ============================================================
    # Objetivo:
    # Si el usuario solo entrega nombre, NIA debe pedir empresa
    # y correo o teléfono, no volver a pedir nombre.
    # ============================================================

    cotizacion_base_2 = process_chat_request(
        ChatRequest(
            mensaje="busco el producto 300203",
            canal="web",
            cliente_id="test_datos_incompletos",
        )
    )

    cotizacion_inicio_2 = process_chat_request(
        ChatRequest(
            mensaje="quiero cotizar este producto",
            session_id=cotizacion_base_2.session_id,
            canal="web",
            cliente_id="test_datos_incompletos",
        )
    )

    datos_incompletos = process_chat_request(
        ChatRequest(
            mensaje="Me llamo Andrea",
            session_id=cotizacion_inicio_2.session_id,
            canal="web",
            cliente_id="test_datos_incompletos",
        )
    )

    print_response(
        "CASO 13 - Pide solo datos comerciales faltantes",
        datos_incompletos,
    )

    assert_condition(
        "Andrea" in datos_incompletos.respuesta,
        "NIA debe reconocer el nombre Andrea.",
    )

    assert_condition(
        "empresa" in datos_incompletos.respuesta.lower(),
        "NIA debe pedir empresa si no fue entregada.",
    )

    assert_condition(
        "correo" in datos_incompletos.respuesta.lower()
        or "teléfono" in datos_incompletos.respuesta.lower()
        or "telefono" in datos_incompletos.respuesta.lower(),
        "NIA debe pedir correo o teléfono si no hay medio de contacto.",
    )

    print("\nFIN TEST CHAT RESPONSE ADAPTER ✅")


if __name__ == "__main__":
    main()