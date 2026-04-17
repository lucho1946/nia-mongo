# ============================================================
# routers/chat.py
# Responsabilidad única: endpoint /chat conversacional.
# Orquesta búsqueda de productos + generación de respuesta IA.
# No contiene lógica de búsqueda ni de conexión — delega todo.
# ============================================================

from fastapi import APIRouter, HTTPException
from models.schemas import ChatRequest
from services.search import buscar_productos
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
    2. Busca productos relevantes en MongoDB
    3. Construye contexto con los productos encontrados
    4. Envía contexto + mensaje a OpenAI
    5. Retorna respuesta de NIA + lista de productos encontrados
    
    Si no hay productos: responde sin llamar a OpenAI (ahorra tokens).
    Si OpenAI falla: retorna 502 con mensaje claro.
    """
    q = p.mensaje.strip()

    # --- FASE 1: Búsqueda de productos ---
    try:
        resultados = buscar_productos(q, limit=8)
    except Exception as e:
        logger.error(f"Error buscando productos para chat: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error consultando el catálogo. Intenta nuevamente."
        )

    # Si no hay resultados no vale la pena llamar a OpenAI
    if not resultados:
        return {
            "respuesta": (
                "No encontré productos en el catálogo que coincidan con tu consulta. "
                "¿Puedes darme más detalles o intentar con otros términos?"
            ),
            "resultados": []
        }

    # --- FASE 2: Construir contexto para OpenAI ---
    # Solo enviamos los campos útiles para la recomendación.
    # Menos tokens = menor costo y respuestas más rápidas.
    contexto = "\n".join([
        f"{i}. "
        f"Nombre: {r.get('nombre', '')} | "
        f"Marca: {r.get('marca', '')} | "
        f"Categoría: {r.get('categoria', '')} | "
        f"Descripción: {r.get('descripcion', '')} | "
        f"Referencia: {r.get('referencia_limpia', '')} | "
        f"Precio: {r.get('precio', 'Consultar')}"
        for i, r in enumerate(resultados, 1)
    ])

    prompt = f"""Consulta del cliente:
{q}

Productos disponibles en el catálogo de VIA Industrial:
{contexto}

Recomienda las opciones más adecuadas para esta consulta, explicando brevemente por qué son relevantes."""

    # --- FASE 3: Llamada a OpenAI ---
    try:
        response = get_ai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,    # Respuestas comerciales concisas
            temperature=0.4,   # Bajo = más consistente, menos alucinaciones
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
        "resultados": resultados
    }