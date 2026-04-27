# ============================================================
# services/search.py
# Responsabilidad única: toda la lógica de búsqueda de productos.
# Tanto el router de productos como el de chat usan este mismo
# servicio — una sola fuente de verdad para buscar.
#
# ACTUALIZACIÓN v0.1:
# Los campos de MongoDB fueron actualizados para coincidir
# exactamente con los nombres del Excel original de VIA Industrial:
#   nombre            → DESCRIPCION_CORTA_PRE
#   descripcion       → DESCRIPCION_LARGA_PRE
#   marca             → MARCA_LET
#   categoria         → NIVEL_1
#   referencia_limpia → REFERENCIA
#   codigo            → CODIGO
#   precio            → PRECIO_VENTA
# Sin este cambio el chatbot no encuentra ningún producto
# aunque el catálogo esté completo en MongoDB.
# ============================================================

import re
import unicodedata
import logging
from rapidfuzz import fuzz
from .mongo import get_collection

logger = logging.getLogger(__name__)


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def normalizar(texto: str) -> str:
    """
    Convierte cualquier texto a minúsculas, sin acentos y sin
    espacios dobles. Ejemplo: 'Válvula   Neumática' → 'valvula neumatica'
    Se aplica tanto a la query del usuario como a los campos del producto
    antes de comparar, para que la búsqueda no falle por tildes o mayúsculas.
    """
    texto = str(texto).lower().strip()
    # NFKD separa la letra base del acento → el combining(c) filtra el acento
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    # Colapsa múltiples espacios en uno solo
    return re.sub(r"\s+", " ", texto)


def extraer_tokens(texto: str) -> list[str]:
    """
    Divide el texto en palabras clave individuales.
    Ejemplo: 'valvula neumatica 1/2' → ['valvula', 'neumatica', '1/2']
    Los tokens se usan para hacer búsquedas campo por campo en Mongo,
    aumentando las chances de encontrar coincidencias parciales.
    """
    tokens = re.findall(r"[a-zA-Z0-9\-\.\/]+", normalizar(texto))
    # Elimina duplicados manteniendo orden, descarta tokens muy cortos
    return list(dict.fromkeys(t for t in tokens if len(t) >= 2))


# ============================================================
# SCORING
# ============================================================

def score_producto(q: str, doc: dict) -> float:
    """
    Calcula qué tan relevante es un producto para la búsqueda.
    Usa RapidFuzz — librería de similitud de texto optimizada en C.

    No es búsqueda exacta: funciona aunque el usuario escriba mal
    o use palabras parciales. Retorna un número entre 0 y 100.

    Campos actualizados a los nombres exactos del Excel original:
    - DESCRIPCION_CORTA_PRE → nombre del producto
    - DESCRIPCION_LARGA_PRE → descripción técnica completa
    - MARCA_LET             → marca del fabricante
    - NIVEL_1               → categoría / línea del producto
    - REFERENCIA            → referencia técnica / SKU
    - REF_ALTERNATIVA       → referencia alternativa
    - CODIGO                → código único del producto

    Pesos definidos por importancia comercial:
    - token_set_ratio (40%): compara conjuntos de palabras, ignora orden
    - partial_ratio (25%):   detecta si la query está contenida en el texto
    - token_sort_ratio (20%): compara nombre ordenando palabras alfabéticamente
    - partial_ratio referencia (15%): prioriza coincidencia en referencia
    """
    qn = normalizar(q)

    # Bloque unificado con todos los campos relevantes del producto
    # Usamos los nombres exactos que están en MongoDB
    bloque = " ".join([
        str(doc.get("DESCRIPCION_CORTA_PRE", "")),
        str(doc.get("DESCRIPCION_LARGA_PRE", "")),
        str(doc.get("REFERENCIA", "")),
        str(doc.get("REF_ALTERNATIVA", "")),
        str(doc.get("MARCA_LET", "")),
        str(doc.get("NIVEL_1", "")),
        str(doc.get("CODIGO", "")),
    ])

    s1 = fuzz.token_set_ratio(qn, bloque)
    s2 = fuzz.partial_ratio(qn, bloque)
    s3 = fuzz.token_sort_ratio(qn, str(doc.get("DESCRIPCION_CORTA_PRE", "")))
    s4 = fuzz.partial_ratio(qn, str(doc.get("REFERENCIA", "")))

    return round((s1 * 0.40) + (s2 * 0.25) + (s3 * 0.20) + (s4 * 0.15), 2)


# ============================================================
# BÚSQUEDA PRINCIPAL
# ============================================================

def buscar_productos(q: str, limit: int = 8) -> list[dict]:
    """
    Función principal de búsqueda. Recibe texto libre del usuario
    y retorna lista de productos ordenados por relevancia.

    Estrategia en dos fases:
    1. MongoDB filtra candidatos con regex (rápido, reduce volumen)
    2. RapidFuzz re-rankea los candidatos (preciso, pero costoso —
       por eso no se aplica a toda la colección)

    Campos de búsqueda actualizados a los nombres exactos del Excel:
    DESCRIPCION_CORTA_PRE, DESCRIPCION_LARGA_PRE, MARCA_LET,
    NIVEL_1, REFERENCIA, REF_ALTERNATIVA, CODIGO
    """
    q_limpia = normalizar(q)
    tokens = extraer_tokens(q_limpia)

    if not tokens:
        return []

    # --- FASE 1: Filtro en MongoDB ---
    # Construimos condiciones OR: si cualquier campo contiene
    # la query completa O cualquiera de los tokens, el documento pasa.
    condiciones = []

    # Campos exactos del Excel original que viven en MongoDB
    campos = [
        "DESCRIPCION_CORTA_PRE",
        "DESCRIPCION_LARGA_PRE",
        "MARCA_LET",
        "NIVEL_1",
        "REFERENCIA",
        "REF_ALTERNATIVA",
        "CODIGO",
    ]

    # Primero intentamos la query completa (más restrictivo, más relevante)
    for campo in campos:
        condiciones.append({campo: {"$regex": re.escape(q_limpia), "$options": "i"}})

    # Luego token por token (más amplio, captura coincidencias parciales)
    for token in tokens:
        for campo in campos:
            condiciones.append({campo: {"$regex": re.escape(token), "$options": "i"}})

    # Solo traemos los campos necesarios — menos datos = más rápido
    # Nombres exactos del Excel original que viven en MongoDB
    proyeccion = {
        "_id": 0,
        "CODIGO": 1,
        "REFERENCIA": 1,
        "REF_ALTERNATIVA": 1,
        "MARCA_LET": 1,
        "DESCRIPCION_CORTA_PRE": 1,
        "DESCRIPCION_LARGA_PRE": 1,
        "PRECIO_VENTA": 1,
        "PV_FECHA": 1,
        "IDN1": 1,
        "NIVEL_1": 1,
        "score": 1,
    }

    try:
        candidatos = list(get_collection().find({"$or": condiciones}, proyeccion))
    except Exception as e:
        logger.error(f"Error MongoDB en buscar_productos: {e}")
        raise

    if not candidatos:
        return []

    # --- FASE 2: Re-ranking con RapidFuzz ---
    # Eliminamos duplicados (mismo CODIGO + DESCRIPCION_CORTA_PRE)
    # y ordenamos por score de mayor a menor
    vistos = set()
    resultados = []

    for doc in sorted(candidatos, key=lambda d: score_producto(q, d), reverse=True):
        clave = (doc.get("CODIGO"), doc.get("DESCRIPCION_CORTA_PRE"))
        if clave not in vistos:
            vistos.add(clave)
            doc["_score_nia"] = score_producto(q, doc)
            resultados.append(doc)

    return resultados[:limit]


# ============================================================
# FORMATO DE SALIDA
# ============================================================

def formatear_producto(p: dict) -> dict:
    """
    Normaliza la estructura de salida de cada producto.
    Mapea los campos internos del Excel al formato estándar
    que consume el frontend y cualquier integración futura
    (WhatsApp, CRM, etc).

    Mapeo de campos Excel/MongoDB → respuesta API:
    CODIGO                → codigo
    DESCRIPCION_CORTA_PRE → nombre
    MARCA_LET             → marca
    NIVEL_1               → categoria
    DESCRIPCION_LARGA_PRE → descripcion (máx 300 chars para no sobrecargar)
    REFERENCIA            → referencia
    PRECIO_VENTA          → precio (formateado en COP con separadores de miles)
    """
    # Formatear precio en COP con separadores de miles
    precio_raw = p.get("PRECIO_VENTA")
    try:
        precio_fmt = f"${float(precio_raw):,.0f} COP" if precio_raw else "Consultar"
    except (ValueError, TypeError):
        precio_fmt = "Consultar"

    return {
        "codigo":      str(p.get("CODIGO", "")).strip(),
        "nombre":      str(p.get("DESCRIPCION_CORTA_PRE", "")).strip(),
        "marca":       str(p.get("MARCA_LET", "")).strip(),
        "categoria":   str(p.get("NIVEL_1", "")).strip(),
        "descripcion": str(p.get("DESCRIPCION_LARGA_PRE", "")).strip()[:300],
        "referencia":  str(p.get("REFERENCIA", "")).strip(),
        "precio":      precio_fmt,
    }