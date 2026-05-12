# ============================================================
# models/schemas.py
# Responsabilidad única: definir la estructura de datos que
# entran y salen de la API.
# Pydantic valida automáticamente — si el dato no cumple,
# FastAPI retorna error 422 antes de llegar al código.
#
# VERSIÓN 0.2:
# - ChatRequest con session_id, canal y cliente_id para flujo conversacional
# - CaracteristicaTecnica flexible para evitar errores 422
# - ProductoResponse con jerarquía completa NIVEL_0 al 4
# - Campos de stock, equivalentes, características técnicas y scoring
# - ChatResponse con estado, session_id y requiere_accion
# - Validación de canal con Literal para evitar valores inválidos
# - Validador de caracteristicas para convertir dicts de MongoDB
# ============================================================

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal


# ============================================================
# REQUEST — Lo que recibe el endpoint /chat
# ============================================================

class ChatRequest(BaseModel):
    """
    Estructura del body que recibe el endpoint /chat.

    session_id:
    - Opcional — si no viene se crea una sesión nueva
    - Si viene, NIA retoma la conversación existente
    - Se valida que tenga formato válido de MongoDB ObjectId

    canal:
    - 'web': desde viaindustrial.com (Fase 1)
    - 'whatsapp': desde WhatsApp (Fase 2)
    - 'api': integración directa (Fase 2)

    cliente_id:
    - Fase 1: 'anonimo' por defecto
    - Fase 2: NIT, celular o nombre de empresa
    """
    mensaje:    str                               = Field(..., min_length=1, max_length=1000)
    session_id: Optional[str]                    = Field(None, description="ID de sesión existente")
    canal:      Literal["web", "whatsapp", "api"] = Field("web", description="Canal de origen")
    cliente_id: str                               = Field("anonimo", description="Identificador del cliente")

    @field_validator("session_id")
    @classmethod
    def validar_session_id(cls, v):
        """
        Valida que el session_id tenga formato válido de MongoDB ObjectId.
        Un ObjectId válido tiene exactamente 24 caracteres hexadecimales.
        Si el formato es inválido retorna None para crear sesión nueva
        en lugar de lanzar un error 422.
        """
        if v is None:
            return None
        v = v.strip()
        # ObjectId de MongoDB: exactamente 24 caracteres hexadecimales
        if len(v) != 24 or not all(c in "0123456789abcdefABCDEF" for c in v):
            return None
        return v


# ============================================================
# CARACTERÍSTICA TÉCNICA — Par título/valor
# ============================================================

class CaracteristicaTecnica(BaseModel):
    """
    Par título/valor de una característica técnica del producto.
    Ejemplo: {"titulo": "Rango de Temperatura", "valor": "-20ºC a 250ºC"}

    Vienen del ETL — construidos desde TIT_CAR_IND_X y CAR_IND_X
    de la tabla productos_hugo en SQL Server de VIA Industrial.

    Todos los campos son Optional con default vacío para evitar
    errores 422 cuando MongoDB retorna datos incompletos.
    """
    titulo: Optional[str] = ""
    valor:  Optional[str] = ""


# ============================================================
# RESPONSE — Estructura estándar de un producto
# ============================================================

class ProductoResponse(BaseModel):
    """
    Estructura estándar de un producto en las respuestas.
    Todos los endpoints devuelven productos con exactamente
    estos campos — consistencia garantizada para el frontend
    y cualquier integración futura (WhatsApp, CRM, etc).

    Todos los campos tienen valores por defecto para evitar
    errores 422 cuando el catálogo tiene datos incompletos.

    IDENTIFICACIÓN:
    codigo          → CODIGO en MongoDB
    referencia      → REFERENCIA en MongoDB
    ref_alternativa → REF_ALTERNATIVA en MongoDB

    DESCRIPCIÓN:
    nombre          → DESCRIPCION_CORTA_PRE en MongoDB
    descripcion     → DESCRIPCION_LARGA_PRE (máx 300 chars)
    marca           → MARCA_LET en MongoDB

    JERARQUÍA COMPLETA VIA INDUSTRIAL:
    nivel_0 → nivel_1 → nivel_2 → nivel_3 → nivel_4
    Categoría → Línea → Sublínea → Producto específico

    COMERCIAL:
    precio          → COP formateado o "Consultarnos" si PV_FECHA > 12 meses
    disponibilidad  → stock real por sede Bogotá y Cali

    TÉCNICO:
    caracteristicas → array de pares título/valor validados
    aplicaciones    → usos del producto
    dimension, peso → datos físicos

    EQUIVALENTES:
    equivalente, equivalente_2 → referencias alternativas

    SCORING COMERCIAL (activo cuando llegue Excel de Don Andrés):
    score_oportunidad → relevancia comercial calculada por Don Andrés
    tipo_sku          → GRAN OPORTUNIDAD, REVISAR, MIXTO, etc
    """

    # Identificación
    codigo:          str = ""
    referencia:      str = ""
    ref_alternativa: str = ""

    # Descripción
    nombre:      str = ""
    descripcion: str = ""
    marca:       str = ""

    # Jerarquía completa VIA Industrial
    # Categoría → Línea → Sublínea → Producto
    nivel_0: str = ""
    nivel_1: str = ""
    nivel_2: str = ""
    nivel_3: str = ""
    nivel_4: str = ""

    # Comercial
    # precio: COP formateado o "Consultarnos" si PV_FECHA > 12 meses
    precio:         str = "Consultarnos"
    disponibilidad: str = "Consultar disponibilidad"
    # Tiempo estimado de entrega — viene del campo EXISTENCIA en SQL Server de VIA
    tiempo_entrega: str = ""

    # Técnico
    caracteristicas: List[CaracteristicaTecnica] = []
    aplicaciones:    str = ""
    dimension:       str = ""
    peso:            Optional[float] = None

    # Equivalentes para ofrecer alternativas al cliente
    equivalente:   str = ""
    equivalente_2: str = ""

    # Scoring comercial VIA Industrial
    # Se activa cuando Don Andrés comparta el Excel del scoring
    score_oportunidad: Optional[float] = None
    tipo_sku:          str = ""

    @field_validator("caracteristicas", mode="before")
    @classmethod
    def limpiar_caracteristicas(cls, v):
        """
        Convierte los diccionarios de MongoDB a CaracteristicaTecnica.
        Maneja casos donde los campos vienen como None o tipo incorrecto.
        Sin este validador Pydantic puede lanzar errores 422 silenciosos
        cuando las características tienen valores nulos o tipos mixtos.
        """
        if not isinstance(v, list):
            return []
        return [
            {
                "titulo": str(c.get("titulo") or ""),
                "valor":  str(c.get("valor")  or "")
            }
            for c in v if isinstance(c, dict)
        ]


# ============================================================
# RESPONSE — Estructura de respuesta del chat
# ============================================================

class ChatResponse(BaseModel):
    """
    Estructura de respuesta del endpoint /chat.

    session_id:
    ID de sesión para que el frontend lo guarde y lo envíe
    en el siguiente mensaje — así NIA recuerda la conversación.

    respuesta:
    Texto de NIA para mostrar al cliente en el chat.

    estado:
    Estado actual de la conversación:
    - 'recopilando': NIA está haciendo preguntas técnicas
    - 'completado': NIA recomendó productos

    preguntas_hechas:
    Cuántas preguntas ha hecho NIA en esta sesión.
    Útil para que el frontend muestre un indicador de progreso.
    Máximo 3 preguntas según propuesta formal del proyecto.

    productos:
    Lista de productos recomendados por NIA.
    Vacío mientras NIA está recopilando contexto.
    Máximo 3 productos según propuesta formal del proyecto.

    requiere_accion:
    Acción especial que el frontend debe ejecutar:
    - None: conversación normal
    - 'escalar_asesor': conectar con asesor humano
    - 'generar_preorden': iniciar proceso de pre-orden (Fase 2)
    """
    session_id:       str
    respuesta:        str
    estado:           str                    = "recopilando"
    preguntas_hechas: int                    = 0
    productos:        List[ProductoResponse] = []
    requiere_accion:  Optional[str]          = None