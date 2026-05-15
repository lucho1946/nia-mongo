# ============================================================
# routers/chat.py
# Responsabilidad única: endpoint /chat conversacional.
# Orquesta el flujo completo de NIA — sesiones, decisión IA,
# búsqueda de productos, generación de respuesta y contexto
# multimodal inicial.
#
# VERSIÓN 0.5 — Correcciones búsqueda multimodal:
# - Query multimodal construido desde datos extraídos del archivo
# - Umbral de confianza >= 40 para usar query multimodal
# - Bloque buscar_productos() correctamente ubicado
# - Indentación corregida en PASO 5B
#
# VERSIÓN 0.4 — Multimodal inicial:
# - Detecta adjuntos desde el request
# - Si existe archivo_ruta, analiza el archivo real con
#   services.multimodal.analizar_archivo_local()
# - Inyecta el contexto multimodal al historial antes de
#   decidir si preguntar o buscar
#
# VERSIÓN 0.3 — Correcciones QA:
# - Manejo correcto de búsqueda sin resultados
# - Mensaje honesto cuando no se encuentra producto o código
#
# VERSIÓN 0.2 — Motor conversacional con sesiones:
# - Gestión de sesiones con TTL de 30 minutos
# - Detección de intención especial (bots, compra, escalación)
# - Decisión inteligente: preguntar o buscar (máximo 3 preguntas)
# - Búsqueda con contexto acumulado de la conversación
# - Respuesta estructurada con ChatResponse
# - Contexto completo para OpenAI: precio, stock, tiempo entrega
#
# FLUJO COMPLETO:
# 1. Recibe mensaje + session_id (opcional)
# 2. Obtiene o crea sesión en MongoDB
# 3. Guarda mensaje en historial
# 4. Si hay archivo, lo analiza con capa multimodal
# 5. Detecta intención especial (bot, compra, escalación)
# 6. Si flujo normal → decidir_accion (preguntar o buscar)
# 7. Si PREGUNTAR → retorna pregunta técnica al cliente
# 8. Si BUSCAR → construye query (multimodal o texto)
# 9. Ejecuta buscar_productos() con el query final
# 10. Si no hay resultados → responde honestamente sin OpenAI
# 11. Genera recomendación con OpenAI + productos reales
# 12. Guarda respuesta en historial y retorna ChatResponse
# ============================================================

import logging

from fastapi import APIRouter, HTTPException

from models.schemas import ChatRequest, ChatResponse, ProductoResponse
from services.search import buscar_productos, formatear_producto
from services.session import (
    crear_sesion,
    obtener_sesion,
    actualizar_sesion,
    agregar_mensaje,
    incrementar_preguntas,
)
from services.ai import (
    decidir_accion,
    generar_recomendacion,
    detectar_intencion_especial,
    RESPUESTA_BOT,
    RESPUESTA_ESCALACION,
    RESPUESTA_PREORDEN,
)
from services.multimodal import (
    analizar_archivo_local,
    detectar_tipo_archivo,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


def construir_contexto_productos(resultados: list) -> str:
    """
    Construye el string de contexto de productos para OpenAI.

    Incluye todos los campos comerciales relevantes:
    código, referencia, precio (con regla PV_FECHA aplicada),
    stock por sede, tiempo de entrega y características técnicas.

    Este contexto es lo que NIA usa para hacer recomendaciones
    precisas y completas al cliente.
    """
    if not resultados:
        return ""

    lineas = []

    for i, r in enumerate(resultados, 1):
        # Usar formatear_producto para aplicar todas las reglas,
        # incluyendo PV_FECHA, stock por sede y tiempo de entrega.
        p = formatear_producto(r)

        # Construir características técnicas como texto resumido.
        caracteristicas_txt = ""
        if p.get("caracteristicas"):
            pares = [
                f"{c.get('titulo', '')}: {c.get('valor', '')}"
                for c in p["caracteristicas"]
                if c.get("titulo") or c.get("valor")
            ]
            if pares:
                caracteristicas_txt = f" | Características: {', '.join(pares[:3])}"

        linea = (
            f"{i}. {p['nombre']} | "
            f"Código: {p['codigo']} | "
            f"Referencia: {p['referencia']} | "
            f"Marca: {p['marca']} | "
            f"Precio: {p['precio']} | "
            f"Disponibilidad: {p['disponibilidad']} | "
            f"Tiempo de entrega: {p['tiempo_entrega'] or 'Consultar'} | "
            f"Categoría: {p['nivel_1']}"
            f"{caracteristicas_txt}"
        )
        lineas.append(linea)

    return "\n".join(lineas)


def construir_contexto_multimodal(contexto: dict) -> str:
    """
    Convierte la extracción multimodal en un texto compacto
    para inyectarlo al historial conversacional.

    La idea es que OpenAI sepa que llegó un archivo y qué
    información relevante se extrajo de él.
    """
    if not contexto:
        return ""

    producto = contexto.get("producto_detectado", {}) or {}
    datos = contexto.get("datos_extraidos", {}) or {}

    lineas = [
        "[CONTEXTO MULTIMODAL]",
        f"Tipo de entrada: {contexto.get('tipo_entrada', '')}",
        f"Tipo de solicitud: {contexto.get('tipo_solicitud', '')}",
        f"Producto detectado: {producto.get('nombre', '')}",
        f"Marca: {producto.get('marca', '')}",
        f"Referencia: {producto.get('referencia', '')}",
        f"Código: {producto.get('codigo', '')}",
        f"Cantidad: {datos.get('cantidad', '')}",
        f"Medidas: {datos.get('medidas', '')}",
        f"Voltaje: {datos.get('voltaje', '')}",
        f"Potencia: {datos.get('potencia', '')}",
        f"Presión: {datos.get('presion', '')}",
        f"Temperatura: {datos.get('temperatura', '')}",
        f"Material: {datos.get('material', '')}",
        f"Aplicación: {datos.get('aplicacion', '')}",
        f"Observaciones: {contexto.get('observaciones', '')}",
        f"Resumen: {contexto.get('texto_resumido', '')}",
        f"Confianza: {contexto.get('confianza', 0)}",
        f"Requiere aclaración: {contexto.get('requiere_aclaracion', False)}",
        f"Pregunta sugerida: {contexto.get('pregunta_sugerida', '')}",
    ]

    return "\n".join(linea for linea in lineas if str(linea).strip())


@router.post("/chat", response_model=ChatResponse)
def chat(p: ChatRequest):
    """
    Endpoint principal del chatbot NIA.

    Recibe:
    - mensaje: texto del cliente
    - session_id: ID de sesión existente (opcional)
    - canal: 'web', 'whatsapp', 'api'
    - cliente_id: identificador del cliente

    Adjuntos:
    - archivo_nombre
    - archivo_tipo
    - archivo_ruta
    - archivo_mimetype

    Retorna ChatResponse con:
    - session_id: para que el frontend lo guarde
    - respuesta: texto de NIA
    - estado: 'recopilando' o 'completado'
    - preguntas_hechas: contador de preguntas
    - productos: lista de ProductoResponse
    - requiere_accion: None, 'escalar_asesor' o 'generar_preorden'
    """
    mensaje = p.mensaje.strip()

    # -------------------------------------------------------
    # PASO EXTRA — Procesamiento multimodal
    #
    # Si el cliente envía un archivo, NIA primero intenta
    # analizarlo con la capa multimodal.
    #
    # Escenario actual:
    # - si existe archivo_ruta → análisis real con OpenAI
    # - si solo existe archivo_nombre → clasificación básica
    # -------------------------------------------------------
    contexto_multimodal = None

    if p.archivo_ruta:
        try:
            contexto_multimodal = analizar_archivo_local(
                p.archivo_ruta,
                mensaje_cliente=mensaje,
            )
            logger.info(
                "Archivo analizado multimodalmente: %s",
                p.archivo_ruta
            )
        except Exception as e:
            logger.error(f"Error procesando archivo multimodal: {e}")
            contexto_multimodal = None

    elif p.archivo_nombre:
        try:
            archivo_detectado = detectar_tipo_archivo(p.archivo_nombre)

            # Contexto mínimo cuando todavía no hay archivo_ruta.
            contexto_multimodal = {
                "tipo_entrada": archivo_detectado.tipo_entrada,
                "tipo_solicitud": "otro",
                "producto_detectado": {
                    "nombre": "",
                    "marca": "",
                    "referencia": "",
                    "codigo": "",
                },
                "datos_extraidos": {
                    "cantidad": "",
                    "medidas": "",
                    "voltaje": "",
                    "potencia": "",
                    "presion": "",
                    "temperatura": "",
                    "material": "",
                    "aplicacion": "",
                },
                "observaciones": "",
                "texto_resumido": "",
                "confianza": 0,
                "requiere_aclaracion": False,
                "pregunta_sugerida": "",
                "archivo": {
                    "nombre_original": archivo_detectado.nombre_original,
                    "nombre_normalizado": archivo_detectado.nombre_normalizado,
                    "extension": archivo_detectado.extension,
                    "mimetype": archivo_detectado.mimetype,
                    "tipo_entrada": archivo_detectado.tipo_entrada,
                    "ruta": archivo_detectado.ruta,
                },
            }

            logger.info(
                "Archivo detectado sin ruta: %s (%s)",
                archivo_detectado.nombre_original,
                archivo_detectado.tipo_entrada
            )

        except Exception as e:
            logger.error(f"Error procesando archivo multimodal: {e}")
            contexto_multimodal = None

    # -------------------------------------------------------
    # PASO 1: Obtener o crear sesión
    # -------------------------------------------------------
    sesion = None

    if p.session_id:
        sesion = obtener_sesion(p.session_id)

    if not sesion:
        sesion = crear_sesion(canal=p.canal, cliente_id=p.cliente_id)
        logger.info(f"Sesión nueva creada: {sesion['_id']}")

    session_id       = sesion["_id"]
    preguntas_hechas = sesion.get("preguntas_hechas", 0)

    # -------------------------------------------------------
    # PASO 2: Guardar mensaje del cliente en historial
    # -------------------------------------------------------
    agregar_mensaje(session_id, "user", mensaje)

    # Obtener historial actualizado para enviarlo a OpenAI
    sesion_actual = obtener_sesion(session_id)
    historial = sesion_actual.get("historial", []) if sesion_actual else [
        {"role": "user", "content": mensaje}
    ]

    # -------------------------------------------------------
    # PASO EXTRA — Inyectar contexto multimodal al historial
    #
    # Permite que OpenAI sepa que el cliente envió un archivo
    # y qué información útil se extrajo de él.
    # -------------------------------------------------------
    if contexto_multimodal:
        contexto_archivo = construir_contexto_multimodal(contexto_multimodal)
        if contexto_archivo.strip():
            historial.append({
                "role": "system",
                "content": contexto_archivo
            })

    # -------------------------------------------------------
    # PASO 3: Detectar intención especial
    # -------------------------------------------------------
    intencion = detectar_intencion_especial(mensaje)

    if intencion == "bot_detectado":
        agregar_mensaje(session_id, "assistant", RESPUESTA_BOT)
        actualizar_sesion(session_id, {"estado": "cerrado"})
        return ChatResponse(
            session_id       = session_id,
            respuesta        = RESPUESTA_BOT,
            estado           = "cerrado",
            preguntas_hechas = preguntas_hechas,
            productos        = [],
            requiere_accion  = None
        )

    if intencion == "escalar_asesor":
        agregar_mensaje(session_id, "assistant", RESPUESTA_ESCALACION)
        return ChatResponse(
            session_id       = session_id,
            respuesta        = RESPUESTA_ESCALACION,
            estado           = "recopilando",
            preguntas_hechas = preguntas_hechas,
            productos        = [],
            requiere_accion  = "escalar_asesor"
        )

    if intencion == "generar_preorden":
        agregar_mensaje(session_id, "assistant", RESPUESTA_PREORDEN)
        return ChatResponse(
            session_id       = session_id,
            respuesta        = RESPUESTA_PREORDEN,
            estado           = "recopilando",
            preguntas_hechas = preguntas_hechas,
            productos        = [],
            requiere_accion  = "generar_preorden"
        )

    # -------------------------------------------------------
    # PASO 4: Decidir si preguntar o buscar
    # -------------------------------------------------------
    try:
        decision = decidir_accion(historial, preguntas_hechas)
    except Exception as e:
        logger.error(f"Error en decidir_accion: {e}")
        raise HTTPException(
            status_code=502,
            detail="Error procesando la consulta. Intenta nuevamente."
        )

    # -------------------------------------------------------
    # PASO 5A: NIA hace una pregunta técnica
    # -------------------------------------------------------
    if decision["accion"] == "PREGUNTAR":
        pregunta = decision["pregunta"]

        agregar_mensaje(session_id, "assistant", pregunta)
        incrementar_preguntas(session_id)

        return ChatResponse(
            session_id       = session_id,
            respuesta        = pregunta,
            estado           = "recopilando",
            preguntas_hechas = preguntas_hechas + 1,
            productos        = [],
            requiere_accion  = None
        )

    # -------------------------------------------------------
    # PASO 5B: Construir query de búsqueda
    #
    # Si hay contexto multimodal con confianza >= 40,
    # construir el query con los datos extraídos del archivo.
    # Esto mejora la relevancia cuando el cliente envía
    # una imagen o PDF de un producto.
    #
    # Si no hay contexto multimodal o la confianza es baja,
    # usar el query que decidió OpenAI o el mensaje original.
    # -------------------------------------------------------
    query_busqueda = decision.get("query", mensaje)

    if contexto_multimodal:
        producto = contexto_multimodal.get("producto_detectado", {}) or {}
        datos    = contexto_multimodal.get("datos_extraidos", {}) or {}

        partes_query = [
            producto.get("nombre",     ""),
            producto.get("marca",      ""),
            producto.get("referencia", ""),
            producto.get("codigo",     ""),
            datos.get("aplicacion",    ""),
        ]

        # Construir query limpio con los datos extraídos
        query_multimodal = " ".join(part for part in partes_query if part.strip())

        # Solo usar query multimodal si tiene contenido útil
        # y confianza suficiente — evita queries vacíos o incorrectos
        confianza = contexto_multimodal.get("confianza", 0)
        if query_multimodal.strip() and confianza >= 40:
            query_busqueda = query_multimodal
            logger.info(f"Query multimodal construido: {query_busqueda} (confianza: {confianza})")
        else:
            logger.info(f"Confianza baja ({confianza}) — usando query original: {query_busqueda}")

    # -------------------------------------------------------
    # PASO 5C: Ejecutar búsqueda con el query final
    # -------------------------------------------------------
    try:
        resultados = buscar_productos(query_busqueda, limit=5)
    except Exception as e:
        logger.error(f"Error buscando productos: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error consultando el catálogo. Intenta nuevamente."
        )

    # -------------------------------------------------------
    # PASO 6: Verificar resultados
    # Si no hay productos NIA responde honestamente
    # sin llamar a OpenAI — ahorra tokens
    # -------------------------------------------------------
    if not resultados:
        respuesta_no_encontrado = (
            "No encontré productos en el catálogo que coincidan con su búsqueda. "
            "¿Puede verificar el código o darme más detalles sobre lo que necesita? "
            "Por ejemplo: nombre del producto, marca o aplicación."
        )
        agregar_mensaje(session_id, "assistant", respuesta_no_encontrado)
        return ChatResponse(
            session_id       = session_id,
            respuesta        = respuesta_no_encontrado,
            estado           = "completado",
            preguntas_hechas = preguntas_hechas,
            productos        = [],
            requiere_accion  = None
        )

    # -------------------------------------------------------
    # PASO 7: Construir contexto y generar recomendación
    # -------------------------------------------------------
    contexto_productos = construir_contexto_productos(resultados)

    try:
        respuesta_texto = generar_recomendacion(historial, contexto_productos)
    except Exception as e:
        logger.error(f"Error generando recomendación: {e}")
        raise HTTPException(
            status_code=502,
            detail="Error generando respuesta. Intenta nuevamente."
        )

    # -------------------------------------------------------
    # PASO 8: Guardar respuesta y actualizar estado sesión
    # -------------------------------------------------------
    agregar_mensaje(session_id, "assistant", respuesta_texto)
    actualizar_sesion(session_id, {"estado": "completado"})

    # Formatear productos para la respuesta
    productos_formateados = [
        ProductoResponse(**formatear_producto(r))
        for r in resultados
    ]

    return ChatResponse(
        session_id       = session_id,
        respuesta        = respuesta_texto,
        estado           = "completado",
        preguntas_hechas = preguntas_hechas,
        productos        = productos_formateados,
        requiere_accion  = None
    )


@router.delete("/chat/{session_id}")
def cerrar_chat(session_id: str):
    """
    Cierra una sesión de chat manualmente.

    El frontend puede llamar esto cuando el cliente cierra el chat.
    En producción con WhatsApp no se usa — el TTL maneja el cierre.
    """
    from services.session import cerrar_sesion
    cerrar_sesion(session_id)
    return {"ok": True, "session_id": session_id}