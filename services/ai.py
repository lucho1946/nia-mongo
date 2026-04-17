# ============================================================
# services/ai.py
# Responsabilidad única: gestionar el cliente OpenAI y el prompt
# del sistema. Si mañana cambias de GPT-4o a otro modelo,
# o ajustas el comportamiento de NIA, lo haces solo aquí.
# ============================================================

from openai import OpenAI
import os
import logging

logger = logging.getLogger(__name__)

# Variable global — mismo patrón lazy que mongo.py.
# Un solo cliente OpenAI por proceso, no uno por request.
_client: OpenAI | None = None


def get_ai_client() -> OpenAI:
    """
    Retorna el cliente OpenAI reutilizable.
    Lee la API key desde variables de entorno.
    Falla rápido si la key no está configurada.
    """
    global _client

    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY no configurado")

        _client = OpenAI(api_key=api_key)
        logger.info("Cliente OpenAI inicializado")

    return _client


# ============================================================
# SYSTEM PROMPT
# Define la personalidad, rol y reglas de comportamiento de NIA.
# Separado del código para que sea fácil de ajustar sin tocar lógica.
# ============================================================

SYSTEM_PROMPT = """Eres NIA, asesora comercial experta de VIA Industrial.

Tu rol:
- Recomendar productos industriales de forma clara, técnica y útil
- Actuar como un asesor de ventas profesional, no como un buscador

Reglas estrictas:
- Responde siempre en español
- Sé directa y profesional, sin rodeos
- Si hay varias opciones relevantes, preséntelas comparando sus diferencias clave
- Si ningún producto es adecuado, dilo con honestidad y sugiere qué información adicional necesitas
- Nunca inventes referencias, precios ni especificaciones que no estén en el contexto entregado
- No menciones que estás usando una base de datos ni que eres una IA, a menos que te lo pregunten directamente
- Mantén un tono cercano pero profesional, orientado a cerrar la venta"""