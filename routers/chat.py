# ============================================================
# routers/chat.py
# Responsabilidad única: endpoint /chat conversacional.
# Orquesta búsqueda de productos + generación de respuesta IA.
# No contiene lógica de búsqueda ni de conexión — delega todo.
#
# ACTUALIZACIÓN v0.1:
# Se actualizó la construcción del contexto para OpenAI usando
# los campos exactos del Excel original que viven en MongoDB:
#   nombre            → DESCRIPCION_CORTA_PRE
#   marca             → MARCA_LET
#   categoria         → NIVEL_1
#   descripcion       → DESCRIPCION_LARGA_PRE
#   referencia_limpia → REFERENCIA
#   precio            → PRECIO_VENTA (formateado en COP)
#
# También se importa formatear_producto para normalizar
# la respuesta de resultados al frontend.
# ============================================================

from fastapi import APIRouter, HTTPException
from models.schemas import ChatRequest
from services.search import buscar_productos, formatear_producto
from services.ai import get_ai_client, SYSTEM_PROMPT
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


@router.post("/chat")
def chat(p: ChatRequest):
    """
    Endpoint principal del chatbot NIA.

    Flujo:
    1. Recibe mensaje del usuario
    2. Busca productos relevantes en MongoDB usando campos exactos del Excel
    3. Construye contexto con los productos encontrados
    4. Envía contexto + mensaje a OpenAI
    5. Retorna respuesta de NIA + lista de productos formateados

    Si no hay productos: responde sin llamar a OpenAI (ahorra tokens).
    Si OpenAI falla: retorna 502 con mensaje claro.
    """
    q = p.mensaje.strip()

    # --- FASE 1: Búsqueda de productos en MongoDB ---
    try:
        resultados = buscar_productos(q, limit=8)
    except Exception as e:
        logger.error(f"Error buscando productos para chat: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error consultando el catálogo. Intenta nuevamente."
        )

    # Si no hay resultados no vale la pena llamar a OpenAI — ahorra tokens
    if not resultados:
        return {
            "respuesta": (
                "Hola, soy NIA, asesora comercial de VIA Industrial. "
                "No encontré productos en el catálogo que coincidan con tu consulta. "
                "¿Puedes darme más detalles sobre lo que necesitas? "
                "Por ejemplo: aplicación, rango de medición, voltaje o tipo de proceso."
            ),
            "resultados": []
        }

    # --- FASE 2: Construir contexto para OpenAI ---
    # Usamos los campos exactos del Excel que viven en MongoDB.
    # Solo enviamos los campos útiles para la recomendación.
    # Menos tokens = menor costo y respuestas más rápidas.
    lineas_contexto = []
    for i, r in enumerate(resultados, 1):
        # Formatear precio en COP con separadores de miles
        precio_raw = r.get("PRECIO_VENTA")
        try:
            precio_str = f"${float(precio_raw):,.0f} COP" if precio_raw else "Consultar"
        except (ValueError, TypeError):
            precio_str = "Consultar"

        linea = (
            f"{i}. "
            f"Nombre: {r.get('DESCRIPCION_CORTA_PRE', '')} | "
            f"Código: {r.get('CODIGO', '')} | "
            f"Referencia: {r.get('REFERENCIA', '')} | "
            f"Marca: {r.get('MARCA_LET', '')} | "
            f"Categoría: {r.get('NIVEL_1', '')} | "
            f"Descripción: {str(r.get('DESCRIPCION_LARGA_PRE', ''))[:200]} | "
            f"Precio: {precio_str}"
        )
        lineas_contexto.append(linea)

    contexto = "\n".join(lineas_contexto)

    prompt = f"""Consulta del cliente:
{q}

Productos disponibles en el catálogo de VIA Industrial:
{contexto}

Recomienda las opciones más adecuadas para esta consulta.
Incluye código, referencia y precio de cada opción recomendada."""

    # --- FASE 3: Llamada a OpenAI ---
    try:
        response = get_ai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=700,    # Respuestas comerciales concisas
            temperature=0.3,   # Bajo = más consistente, menos alucinaciones
        )
        respuesta_texto = response.choices[0].message.content

    except Exception as e:
        logger.error(f"Error OpenAI en /chat: {e}")
        raise HTTPException(
            status_code=502,
            detail="Error generando respuesta. Intenta nuevamente."
        )

    return {
        "respuesta": respuesta_texto,
        "resultados": [formatear_producto(r) for r in resultados]
    }