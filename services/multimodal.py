# ============================================================
# services/multimodal.py
# Responsabilidad única:
# - detectar el tipo de archivo que envía el cliente
# - preparar el adjunto para análisis multimodal
# - extraer contenido estructurado desde imágenes, PDFs y documentos
#
# FLUJO:
# 1. Detecta el tipo de archivo
# 2. Convierte el archivo a base64
# 3. Envía el contenido a OpenAI Responses API
# 4. Recibe una salida estructurada JSON
# 5. Devuelve una estructura estándar para NIA
#
# NOTA IMPORTANTE:
# - PDFs con visión: extraen texto + imágenes de página
# - Documentos no PDF: extraen texto solamente
# - Imágenes: se analizan como input_image
# - Si el archivo es "otro", se devuelve una extracción vacía
# ============================================================

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI

logger = logging.getLogger(__name__)

# ============================================================
# CLIENTE OPENAI
# ============================================================

_client: OpenAI | None = None


def get_ai_client() -> OpenAI:
    """
    Retorna un cliente OpenAI reutilizable.
    Patrón lazy: se crea solo cuando se necesita por primera vez.
    """
    global _client

    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY no configurado. "
                "Agrégalo en las variables de entorno."
            )
        _client = OpenAI(api_key=api_key)
        logger.info("Cliente OpenAI inicializado para multimodalidad")

    return _client


# ============================================================
# TIPOS DE ENTRADA
# ============================================================

TipoEntrada = Literal["imagen", "pdf", "documento", "otro"]


# ============================================================
# MODELO DE ARCHIVO DETECTADO
# ============================================================

@dataclass
class ArchivoDetectado:
    """
    Representa un archivo recibido por NIA ya clasificado.
    """
    nombre_original: str
    nombre_normalizado: str
    extension: str
    mimetype: str
    tipo_entrada: TipoEntrada
    ruta: str | None = None


# ============================================================
# MODELO DE EXTRACCIÓN MULTIMODAL
# ============================================================

@dataclass
class ExtraccionMultimodal:
    """
    Estructura estándar que NIA devolverá después de analizar
    una imagen, PDF o documento.
    """
    tipo_entrada: TipoEntrada
    tipo_solicitud: str
    producto_detectado: dict[str, str]
    datos_extraidos: dict[str, str]
    observaciones: str
    texto_resumido: str
    confianza: int
    requiere_aclaracion: bool
    pregunta_sugerida: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# UTILIDADES
# ============================================================

def normalizar_nombre_archivo(nombre: str) -> str:
    """
    Limpia el nombre del archivo para uso interno.
    """
    nombre = nombre.strip().replace("\\", "/")
    return Path(nombre).name


def _mimetype_por_extension(extension: str) -> str:
    """
    Devuelve un MIME type razonable según la extensión.
    """
    extension = extension.lower().lstrip(".")

    mapa = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "rtf": "application/rtf",
        "odt": "application/vnd.oasis.opendocument.text",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
    }

    return mapa.get(extension, mimetypes.guess_type(f"archivo.{extension}")[0] or "application/octet-stream")


def detectar_tipo_archivo(nombre_archivo: str) -> ArchivoDetectado:
    """
    Detecta el tipo de archivo según su extensión.
    """
    nombre_limpio = normalizar_nombre_archivo(nombre_archivo)
    extension = Path(nombre_limpio).suffix.lower().lstrip(".")
    mimetype = _mimetype_por_extension(extension)

    if extension in {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"}:
        tipo = "imagen"
    elif extension == "pdf":
        tipo = "pdf"
    elif extension in {"doc", "docx", "txt", "rtf", "odt", "xls", "xlsx", "csv"}:
        tipo = "documento"
    else:
        tipo = "otro"

    return ArchivoDetectado(
        nombre_original=nombre_archivo,
        nombre_normalizado=nombre_limpio,
        extension=extension,
        mimetype=mimetype,
        tipo_entrada=tipo,
        ruta=None,
    )


def preparar_archivo_para_analisis(ruta_archivo: str | Path) -> ArchivoDetectado:
    """
    Prepara un archivo que ya existe en disco para ser analizado.
    """
    ruta = Path(ruta_archivo)

    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    archivo = detectar_tipo_archivo(ruta.name)
    archivo.ruta = str(ruta.resolve())
    return archivo


def _leer_archivo_base64(ruta_archivo: str | Path) -> str:
    """
    Lee el archivo y lo convierte a base64.
    """
    ruta = Path(ruta_archivo)

    with ruta.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _schema_extraccion() -> dict[str, Any]:
    """
    JSON Schema usado para Structured Outputs.
    Mantiene la salida de NIA consistente y fácil de consumir.
    """
    return {
        "type": "object",
        "properties": {
            "tipo_entrada": {
                "type": "string",
                "enum": ["imagen", "pdf", "documento", "otro"]
            },
            "tipo_solicitud": {
                "type": "string",
                "enum": [
                    "busqueda_producto",
                    "cotizacion",
                    "consulta_tecnica",
                    "referencia_parcial",
                    "repuesto",
                    "otro"
                ]
            },
            "producto_detectado": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string"},
                    "marca": {"type": "string"},
                    "referencia": {"type": "string"},
                    "codigo": {"type": "string"}
                },
                "required": ["nombre", "marca", "referencia", "codigo"],
                "additionalProperties": False
            },
            "datos_extraidos": {
                "type": "object",
                "properties": {
                    "cantidad": {"type": "string"},
                    "medidas": {"type": "string"},
                    "voltaje": {"type": "string"},
                    "potencia": {"type": "string"},
                    "presion": {"type": "string"},
                    "temperatura": {"type": "string"},
                    "material": {"type": "string"},
                    "aplicacion": {"type": "string"}
                },
                "required": [
                    "cantidad",
                    "medidas",
                    "voltaje",
                    "potencia",
                    "presion",
                    "temperatura",
                    "material",
                    "aplicacion"
                ],
                "additionalProperties": False
            },
            "observaciones": {"type": "string"},
            "texto_resumido": {"type": "string"},
            "confianza": {"type": "integer"},
            "requiere_aclaracion": {"type": "boolean"},
            "pregunta_sugerida": {"type": "string"}
        },
        "required": [
            "tipo_entrada",
            "tipo_solicitud",
            "producto_detectado",
            "datos_extraidos",
            "observaciones",
            "texto_resumido",
            "confianza",
            "requiere_aclaracion",
            "pregunta_sugerida"
        ],
        "additionalProperties": False
    }


def crear_extraccion_vacia(tipo_entrada: TipoEntrada) -> dict[str, Any]:
    """
    Crea una extracción vacía con formato estándar.
    """
    return ExtraccionMultimodal(
        tipo_entrada=tipo_entrada,
        tipo_solicitud="otro",
        producto_detectado={
            "nombre": "",
            "marca": "",
            "referencia": "",
            "codigo": "",
        },
        datos_extraidos={
            "cantidad": "",
            "medidas": "",
            "voltaje": "",
            "potencia": "",
            "presion": "",
            "temperatura": "",
            "material": "",
            "aplicacion": "",
        },
        observaciones="",
        texto_resumido="",
        confianza=0,
        requiere_aclaracion=False,
        pregunta_sugerida="",
    ).to_dict()


def _normalizar_salida_json(data: dict[str, Any], tipo_entrada: TipoEntrada) -> dict[str, Any]:
    """
    Asegura que el JSON devuelto siempre tenga las claves esperadas.
    """
    producto = data.get("producto_detectado") or {}
    datos = data.get("datos_extraidos") or {}

    salida = ExtraccionMultimodal(
        tipo_entrada=data.get("tipo_entrada", tipo_entrada),
        tipo_solicitud=data.get("tipo_solicitud", "otro"),
        producto_detectado={
            "nombre": str(producto.get("nombre") or ""),
            "marca": str(producto.get("marca") or ""),
            "referencia": str(producto.get("referencia") or ""),
            "codigo": str(producto.get("codigo") or ""),
        },
        datos_extraidos={
            "cantidad": str(datos.get("cantidad") or ""),
            "medidas": str(datos.get("medidas") or ""),
            "voltaje": str(datos.get("voltaje") or ""),
            "potencia": str(datos.get("potencia") or ""),
            "presion": str(datos.get("presion") or ""),
            "temperatura": str(datos.get("temperatura") or ""),
            "material": str(datos.get("material") or ""),
            "aplicacion": str(datos.get("aplicacion") or ""),
        },
        observaciones=str(data.get("observaciones") or ""),
        texto_resumido=str(data.get("texto_resumido") or ""),
        confianza=int(data.get("confianza") or 0),
        requiere_aclaracion=bool(data.get("requiere_aclaracion") or False),
        pregunta_sugerida=str(data.get("pregunta_sugerida") or ""),
    )

    return salida.to_dict()


# ============================================================
# EXTRACCIÓN REAL CON OPENAI
# ============================================================

def extraer_contexto_multimodal(
    ruta_archivo: str | Path,
    mensaje_cliente: str = "",
    modelo: str | None = None,
) -> dict[str, Any]:
    """
    Extrae contexto estructurado desde una imagen, PDF o documento.

    Usa:
    - input_image para imágenes
    - input_file para PDFs y documentos
    - Structured Outputs con JSON Schema
    """
    archivo = preparar_archivo_para_analisis(ruta_archivo)

    if archivo.tipo_entrada == "otro":
        return crear_extraccion_vacia("otro")

    base64_data = _leer_archivo_base64(archivo.ruta or ruta_archivo)
    modelo = modelo or os.getenv("OPENAI_MULTIMODAL_MODEL", "gpt-4o-mini")

    prompt = (
        "Eres NIA, asistente comercial de VIA Industrial. "
        "Analiza el archivo y extrae solo información útil para ventas industriales. "
        "No inventes datos. Si algo no es claro, déjalo vacío y activa requiere_aclaracion. "
        "Si detectas una referencia, marca, modelo, código o contexto de compra, "
        "resúmelo de forma breve y precisa."
    )

    if mensaje_cliente.strip():
        prompt += f"\n\nMensaje del cliente:\n{mensaje_cliente.strip()}"

    schema = _schema_extraccion()

    try:
        client = get_ai_client()

        if archivo.tipo_entrada == "imagen":
            # Imágenes: Responses API con input_image
            response = client.responses.create(
                model=modelo,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": f"data:{archivo.mimetype};base64,{base64_data}",
                            },
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "nia_multimodal_extraction",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
        else:
            # PDFs y documentos: input_file
            # PDF con modelos con visión -> texto + imágenes de página
            # Documentos no PDF -> texto únicamente
            response = client.responses.create(
                model=modelo,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_file",
                                "filename": archivo.nombre_normalizado,
                                "file_data": f"data:{archivo.mimetype};base64,{base64_data}",
                            },
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "nia_multimodal_extraction",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )

        texto = getattr(response, "output_text", "") or ""

        if not texto.strip():
            logger.warning("La respuesta multimodal llegó vacía")
            return crear_extraccion_vacia(archivo.tipo_entrada)

        try:
            data = json.loads(texto)
        except json.JSONDecodeError:
            logger.warning("La respuesta multimodal no fue JSON válido")
            return crear_extraccion_vacia(archivo.tipo_entrada)

        salida = _normalizar_salida_json(data, archivo.tipo_entrada)

        salida["archivo"] = {
            "nombre_original": archivo.nombre_original,
            "nombre_normalizado": archivo.nombre_normalizado,
            "extension": archivo.extension,
            "mimetype": archivo.mimetype,
            "tipo_entrada": archivo.tipo_entrada,
            "ruta": archivo.ruta,
        }

        return salida

    except Exception as e:
        logger.error(f"Error en extraer_contexto_multimodal: {e}")
        return crear_extraccion_vacia(archivo.tipo_entrada)


# ============================================================
# FUNCIÓN DE APOYO PARA INTEGRACIÓN PROGRESIVA
# ============================================================

def analizar_archivo_local(
    ruta_archivo: str | Path,
    mensaje_cliente: str = "",
    modelo: str | None = None,
) -> dict[str, Any]:
    """
    Punto de entrada recomendado para el backend.

    Detecta el archivo y extrae contexto en un solo paso.
    """
    return extraer_contexto_multimodal(
        ruta_archivo=ruta_archivo,
        mensaje_cliente=mensaje_cliente,
        modelo=modelo,
    )


# ============================================================
# EJEMPLO DE USO
# ============================================================
#
# salida = analizar_archivo_local(
#     "cotizacion_cliente.pdf",
#     mensaje_cliente="Necesito este producto"
# )
# print(salida)
#
# En el siguiente paso conectamos esta salida con chat.py
# para inyectarla al historial y luego cruzarla con el catálogo.
# ============================================================