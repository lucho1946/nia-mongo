# ============================================================
# models/schemas.py
# Responsabilidad única: definir la estructura de datos que
# entran y salen de la API.
# Pydantic valida automáticamente — si el dato no cumple,
# FastAPI retorna error 422 antes de llegar al código.
# ============================================================

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """
    Estructura del body que recibe el endpoint /chat.
    El usuario envía un JSON con el campo 'mensaje'.
    
    Field valida:
    - min_length=1 → no acepta mensajes vacíos
    - max_length=1000 → evita abusos o prompts gigantes que
      consuman tokens de OpenAI innecesariamente
    """
    mensaje: str = Field(..., min_length=1, max_length=1000)


class ProductoResponse(BaseModel):
    """
    Estructura estándar de un producto en las respuestas.
    Todos los endpoints devuelven productos con exactamente
    estos campos — consistencia garantizada para el frontend
    y cualquier integración futura.
    """
    codigo: str
    nombre: str
    marca: str
    categoria: str
    descripcion: str
    referencia: str
    precio: str