# ============================================================
# models/schemas.py
# ============================================================
# Responsabilidad única: definir la estructura de datos que
# entran y salen de la API.
#
# Pydantic valida automáticamente:
# - si el dato no cumple el esquema,
# - FastAPI responde 422 antes de ejecutar lógica.
#
# VERSIÓN 0.4:
# - Soporte para session_id Mongo ObjectId y UUID.
# - Necesario para migrar /chat al orquestador NIA OS.
# - Mantiene compatibilidad con frontend actual.
# - Soporte inicial para adjuntos multimodales.
# ============================================================

from __future__ import annotations

import re
from typing import Optional, List, Literal

from pydantic import BaseModel, Field, field_validator


# ============================================================
# REQUEST — Lo que recibe el endpoint /chat
# ============================================================

class ChatRequest(BaseModel):
    """
    Body principal del endpoint /chat.

    Fase actual:
    - conversación textual
    - sesiones persistentes / temporales
    - soporte inicial para adjuntos

    Importante:
    - El flujo anterior usaba ObjectId de MongoDB.
    - El orquestador NIA OS usa UUID.
    - Este esquema acepta ambos formatos para no romper sesión.
    """

    mensaje: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Mensaje principal enviado por el cliente",
    )

    session_id: Optional[str] = Field(
        None,
        description="ID de sesión existente. Acepta ObjectId MongoDB o UUID.",
    )

    canal: Literal["web", "whatsapp", "api"] = Field(
        "web",
        description="Canal desde donde llega el mensaje",
    )

    cliente_id: str = Field(
        "anonimo",
        description="Identificador del cliente",
    )

    archivo_nombre: Optional[str] = Field(
        None,
        description="Nombre original del archivo",
    )

    archivo_tipo: Optional[str] = Field(
        None,
        description="Tipo del archivo: imagen, pdf, documento",
    )

    archivo_ruta: Optional[str] = Field(
        None,
        description="Ruta local o URL temporal del archivo",
    )

    archivo_mimetype: Optional[str] = Field(
        None,
        description="MIME type del archivo",
    )

    @field_validator("session_id")
    @classmethod
    def validar_session_id(cls, v):
        """
        Valida session_id sin romper compatibilidad.

        Acepta:
        - ObjectId MongoDB de 24 caracteres hexadecimales.
        - UUID estándar de 36 caracteres.

        Si es inválido:
        - retorna None
        - se crea sesión nueva
        """
        if v is None:
            return None

        value = str(v).strip()

        if not value:
            return None

        # ObjectId MongoDB
        if len(value) == 24 and all(c in "0123456789abcdefABCDEF" for c in value):
            return value

        # UUID estándar
        uuid_pattern = (
            r"^[0-9a-fA-F]{8}-"
            r"[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}$"
        )

        if re.match(uuid_pattern, value):
            return value

        return None

    @field_validator("archivo_tipo")
    @classmethod
    def normalizar_archivo_tipo(cls, v):
        """
        Normaliza el tipo de archivo.
        """
        if v is None:
            return None

        return str(v).strip().lower() or None


# ============================================================
# CARACTERÍSTICAS TÉCNICAS
# ============================================================

class CaracteristicaTecnica(BaseModel):
    """
    Par título/valor técnico del producto.
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

    codigo: str = ""
    referencia: str = ""
    ref_alternativa: str = ""

    nombre: str = ""
    descripcion: str = ""
    marca: str = ""

    nivel_0: str = ""
    nivel_1: str = ""
    nivel_2: str = ""
    nivel_3: str = ""
    nivel_4: str = ""

    precio: str = "Consultarnos"
    disponibilidad: str = "Consultar disponibilidad"
    tiempo_entrega: str = ""

    caracteristicas: List[CaracteristicaTecnica] = Field(default_factory=list)
    aplicaciones: str = ""

    dimension: str = ""
    peso: Optional[float] = None

    equivalente: str = ""
    equivalente_2: str = ""

    score_oportunidad: Optional[float] = None
    tipo_sku: str = ""

    @field_validator("caracteristicas", mode="before")
    @classmethod
    def limpiar_caracteristicas(cls, v):
        """
        Limpia estructuras inconsistentes provenientes de MongoDB.
        """
        if not isinstance(v, list):
            return []

        cleaned = []

        for item in v:
            if isinstance(item, dict):
                cleaned.append({
                    "titulo": str(item.get("titulo") or item.get("title") or ""),
                    "valor": str(item.get("valor") or item.get("value") or ""),
                })
            else:
                cleaned.append({
                    "titulo": "",
                    "valor": str(item),
                })

        return cleaned


# ============================================================
# CHAT RESPONSE
# ============================================================

class ChatResponse(BaseModel):
    """
    Respuesta estándar del endpoint /chat.

    Mantiene compatibilidad con frontend actual y además expone
    metadata comercial útil para integración futura con asesor,
    CRM, Bitrix o panel comercial.
    """

    session_id: str
    respuesta: str
    estado: str = "recopilando"
    preguntas_hechas: int = 0
    productos: List[ProductoResponse] = Field(default_factory=list)
    requiere_accion: Optional[str] = None

    # ------------------------------------------------------------
    # Metadata comercial / Commercial Spine
    # ------------------------------------------------------------
    estado_negociacion: Optional[str] = None
    commercial_process_state: Optional[str] = None
    siguiente_paso: Optional[str] = None
    datos_faltantes: List[str] = Field(default_factory=list)
    datos_faltantes_proforma: List[str] = Field(default_factory=list)

    # ------------------------------------------------------------
    # Handoff comercial estructurado
    # ------------------------------------------------------------
    # Usamos "dict" nativo en vez de Dict[str, Any] para evitar
    # problemas de forward references de Pydantic con __future__.annotations.
    # El contenido ya viene validado desde commercial_handoff.py.
    # ------------------------------------------------------------
    commercial_handoff: Optional[dict] = None