# ============================================================
# models/schemas.py
# Responsabilidad única: definir la estructura de datos que
# entran y salen de la API.
#
# Pydantic valida automáticamente:
# - si el dato no cumple el esquema,
# - FastAPI responde 422 antes de ejecutar lógica.
#
# VERSIÓN 0.3:
# - Soporte inicial para adjuntos multimodales
# - ChatRequest admite archivos opcionales
# - Compatibilidad total con el flujo actual
# - default_factory=list para evitar listas compartidas
# ============================================================

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal


# ============================================================
# REQUEST — Lo que recibe el endpoint /chat
# ============================================================

class ChatRequest(BaseModel):
    """
    Body principal del endpoint /chat.

    Fase actual:
    - conversación textual
    - sesiones persistentes
    - soporte inicial para adjuntos

    Futuro:
    - imágenes
    - PDFs
    - documentos técnicos
    - multimodalidad completa
    """

    # ========================================================
    # MENSAJE PRINCIPAL
    # ========================================================

    mensaje: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Mensaje principal enviado por el cliente"
    )

    # ========================================================
    # SESIÓN CONVERSACIONAL
    # ========================================================

    session_id: Optional[str] = Field(
        None,
        description="ID de sesión existente"
    )

    # ========================================================
    # CANAL DE ORIGEN
    # ========================================================

    canal: Literal["web", "whatsapp", "api"] = Field(
        "web",
        description="Canal desde donde llega el mensaje"
    )

    # ========================================================
    # IDENTIFICACIÓN CLIENTE
    # ========================================================

    cliente_id: str = Field(
        "anonimo",
        description="Identificador del cliente"
    )

    # ========================================================
    # CAMPOS MULTIMODALES — FASE 3
    # ========================================================
    #
    # Estos campos preparan a NIA para:
    # - imágenes
    # - PDFs
    # - documentos técnicos
    # - archivos enviados por clientes
    #
    # Aún no procesan el archivo;
    # solo permiten recibir información del adjunto.
    # ========================================================

    archivo_nombre: Optional[str] = Field(
        None,
        description="Nombre original del archivo"
    )

    archivo_tipo: Optional[str] = Field(
        None,
        description="Tipo del archivo: imagen, pdf, documento"
    )

    archivo_ruta: Optional[str] = Field(
        None,
        description="Ruta local o URL temporal del archivo"
    )

    archivo_mimetype: Optional[str] = Field(
        None,
        description="MIME type del archivo"
    )

    # ========================================================
    # VALIDADORES
    # ========================================================

    @field_validator("session_id")
    @classmethod
    def validar_session_id(cls, v):
        """
        Valida formato MongoDB ObjectId.

        Si es inválido:
        - NO rompe el request
        - retorna None
        - se crea sesión nueva
        """
        if v is None:
            return None

        v = v.strip()

        if len(v) != 24:
            return None

        if not all(c in "0123456789abcdefABCDEF" for c in v):
            return None

        return v

    @field_validator("archivo_tipo")
    @classmethod
    def normalizar_archivo_tipo(cls, v):
        """
        Normaliza el tipo de archivo.
        """
        if v is None:
            return None

        return v.strip().lower() or None


# ============================================================
# CARACTERÍSTICAS TÉCNICAS
# ============================================================

class CaracteristicaTecnica(BaseModel):
    """
    Par título/valor técnico del producto.

    Ejemplo:
    {
        "titulo": "Voltaje",
        "valor": "220V"
    }
    """

    titulo: Optional[str] = ""
    valor: Optional[str] = ""


# ============================================================
# PRODUCTO RESPONSE
# ============================================================

class ProductoResponse(BaseModel):
    """
    Estructura estándar de producto devuelta por NIA.

    Mantiene consistencia entre:
    - frontend
    - API
    - WhatsApp futuro
    - CRM futuro
    """

    # ========================================================
    # IDENTIFICACIÓN
    # ========================================================

    codigo: str = ""
    referencia: str = ""
    ref_alternativa: str = ""

    # ========================================================
    # DESCRIPCIÓN
    # ========================================================

    nombre: str = ""
    descripcion: str = ""
    marca: str = ""

    # ========================================================
    # JERARQUÍA VIA INDUSTRIAL
    # ========================================================

    nivel_0: str = ""
    nivel_1: str = ""
    nivel_2: str = ""
    nivel_3: str = ""
    nivel_4: str = ""

    # ========================================================
    # INFORMACIÓN COMERCIAL
    # ========================================================

    precio: str = "Consultarnos"

    disponibilidad: str = "Consultar disponibilidad"

    tiempo_entrega: str = ""

    # ========================================================
    # INFORMACIÓN TÉCNICA
    # ========================================================

    caracteristicas: List[CaracteristicaTecnica] = Field(
        default_factory=list
    )

    aplicaciones: str = ""

    dimension: str = ""

    peso: Optional[float] = None

    # ========================================================
    # EQUIVALENTES
    # ========================================================

    equivalente: str = ""

    equivalente_2: str = ""

    # ========================================================
    # SCORING COMERCIAL
    # ========================================================

    score_oportunidad: Optional[float] = None

    tipo_sku: str = ""

    # ========================================================
    # VALIDADORES
    # ========================================================

    @field_validator("caracteristicas", mode="before")
    @classmethod
    def limpiar_caracteristicas(cls, v):
        """
        Limpia estructuras inconsistentes provenientes de MongoDB.
        """
        if not isinstance(v, list):
            return []

        return [
            {
                "titulo": str(c.get("titulo") or ""),
                "valor": str(c.get("valor") or "")
            }
            for c in v
            if isinstance(c, dict)
        ]


# ============================================================
# CHAT RESPONSE
# ============================================================

class ChatResponse(BaseModel):
    """
    Respuesta estándar del endpoint /chat.
    """

    # ========================================================
    # IDENTIFICACIÓN SESIÓN
    # ========================================================

    session_id: str

    # ========================================================
    # RESPUESTA NIA
    # ========================================================

    respuesta: str

    # ========================================================
    # ESTADO CONVERSACIÓN
    # ========================================================

    estado: str = "recopilando"

    # ========================================================
    # CONTROL DE PREGUNTAS
    # ========================================================

    preguntas_hechas: int = 0

    # ========================================================
    # PRODUCTOS RECOMENDADOS
    # ========================================================

    productos: List[ProductoResponse] = Field(
        default_factory=list
    )

    # ========================================================
    # ACCIONES ESPECIALES
    # ========================================================

    requiere_accion: Optional[str] = None