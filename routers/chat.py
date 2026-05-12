# ============================================================
# routers/chat.py
# Responsabilidad única: endpoint /chat conversacional.
# Orquesta el flujo completo de NIA — sesiones, decisión IA,
# búsqueda de productos y generación de respuesta.
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
# 4. Detecta intención especial (bot, compra, escalación)
# 5. Si flujo normal → decidir_accion (preguntar o buscar)
# 6. Si PREGUNTAR → retorna pregunta técnica al cliente
# 7. Si BUSCAR → busca en MongoDB con contexto acumulado
# 8. Genera recomendación con OpenAI + productos reales
# 9. Guarda respuesta en historial y retorna ChatResponse
# ============================================================

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
import logging

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
        # Usar formatear_producto para aplicar todas las reglas
        # incluyendo PV_FECHA, stock por sede y tiempo de entrega
        p = formatear_producto(r)

        # Construir características técnicas como texto
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


@router.post("/chat", response_model=ChatResponse)
def chat(p: ChatRequest):
    """
    Endpoint principal del chatbot NIA.

    Recibe:
    - mensaje: texto del cliente
    - session_id: ID de sesión existente (opcional)
    - canal: 'web', 'whatsapp', 'api'
    - cliente_id: identificador del cliente (Fase 1: 'anonimo')

    Retorna ChatResponse con:
    - session_id: para que el frontend lo guarde
    - respuesta: texto de NIA
    - estado: 'recopilando' o 'completado'
    - preguntas_hechas: contador de preguntas
    - productos: lista de ProductoResponse (vacío si aún pregunta)
    - requiere_accion: None, 'escalar_asesor' o 'generar_preorden'
    """
    mensaje = p.mensaje.strip()

    # -------------------------------------------------------
    # PASO 1: Obtener o crear sesión
    # -------------------------------------------------------
    sesion = None

    if p.session_id:
        sesion = obtener_sesion(p.session_id)

    if not sesion:
        # Crear sesión nueva si no existe o expiró
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
    historial     = sesion_actual.get("historial", []) if sesion_actual else [
        {"role": "user", "content": mensaje}
    ]

    # -------------------------------------------------------
    # PASO 3: Detectar intención especial
    # -------------------------------------------------------
    intencion = detectar_intencion_especial(mensaje)

    if intencion == "bot_detectado":
        agregar_mensaje(session_id, "assistant", RESPUESTA_BOT)
        actualizar_sesion(session_id, {"estado": "cerrado"})
        return ChatResponse(
            session_id      = session_id,
            respuesta       = RESPUESTA_BOT,
            estado          = "cerrado",
            preguntas_hechas = preguntas_hechas,
            productos       = [],
            requiere_accion = None
        )

    if intencion == "escalar_asesor":
        agregar_mensaje(session_id, "assistant", RESPUESTA_ESCALACION)
        return ChatResponse(
            session_id      = session_id,
            respuesta       = RESPUESTA_ESCALACION,
            estado          = "recopilando",
            preguntas_hechas = preguntas_hechas,
            productos       = [],
            requiere_accion = "escalar_asesor"
        )

    if intencion == "generar_preorden":
        agregar_mensaje(session_id, "assistant", RESPUESTA_PREORDEN)
        return ChatResponse(
            session_id      = session_id,
            respuesta       = RESPUESTA_PREORDEN,
            estado          = "recopilando",
            preguntas_hechas = preguntas_hechas,
            productos       = [],
            requiere_accion = "generar_preorden"
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
    # PASO 5B: NIA busca productos en MongoDB
    # -------------------------------------------------------
    query_busqueda = decision.get("query", mensaje)

    try:
        resultados = buscar_productos(query_busqueda, limit=5)
    except Exception as e:
        logger.error(f"Error buscando productos: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error consultando el catálogo. Intenta nuevamente."
        )

    # -------------------------------------------------------
    # PASO 6: Construir contexto y generar recomendación
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
    # PASO 7: Guardar respuesta y actualizar estado sesión
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