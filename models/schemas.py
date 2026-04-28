# ============================================================
# models/schemas.py
# Responsabilidad única: definir la estructura de datos que
# entran y salen de la API.
# Pydantic valida automáticamente — si el dato no cumple,
# FastAPI retorna error 422 antes de llegar al código.
#
# ACTUALIZACIÓN v0.1:
# ProductoResponse fue actualizado para reflejar los campos
# reales del catálogo de VIA Industrial — coinciden exactamente
# con los nombres del Excel original y con lo que retorna
# formatear_producto() en services/search.py.
# ============================================================

from pydantic import BaseModel, Field
from typing import Optional


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
    y cualquier integración futura (WhatsApp, CRM, etc).

    Mapeo de campos Excel/MongoDB → API:
    CODIGO                → codigo
    DESCRIPCION_CORTA_PRE → nombre
    MARCA_LET             → marca
    NIVEL_1               → categoria
    DESCRIPCION_LARGA_PRE → descripcion (máx 300 chars)
    REFERENCIA            → referencia
    PRECIO_VENTA          → precio (formateado en COP)

    Los campos Optional permiten que el producto se retorne
    aunque algún campo esté vacío en el catálogo — evita
    errores 422 por datos incompletos.
    """
    codigo:      str
    nombre:      str
    marca:       str
    categoria:   str
    descripcion: str
    referencia:  str
    precio:      str