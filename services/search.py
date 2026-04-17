# ============================================================
# services/search.py
# Responsabilidad única: toda la lógica de búsqueda de productos.
# Tanto el router de productos como el de chat usan este mismo
# servicio — una sola fuente de verdad para buscar.
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
    
    Pesos definidos por importancia comercial:
    - token_set_ratio (40%): compara conjuntos de palabras, ignora orden
    - partial_ratio (25%):   detecta si la query está contenida en el texto
    - token_sort_ratio (20%): compara nombre ordenando palabras alfabéticamente
    - partial_ratio referencia (15%): prioriza coincidencia en código/referencia
    """
    qn = normalizar(q)

    # Armamos un bloque de texto con todos los campos relevantes del producto
    bloque = " ".join([
        str(doc.get("nombre", "")),
        str(doc.get("descripcion", "")),
        str(doc.get("texto_buscado_expandido", "")),
        str(doc.get("referencia_limpia", "")),
        str(doc.get("marca", "")),
        str(doc.get("categoria", "")),
    ])

    s1 = fuzz.token_set_ratio(qn, bloque)
    s2 = fuzz.partial_ratio(qn, bloque)
    s3 = fuzz.token_sort_ratio(qn, str(doc.get("nombre", "")))
    s4 = fuzz.partial_ratio(qn, str(doc.get("referencia_limpia", "")))

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
    """
    q_limpia = normalizar(q)
    tokens = extraer_tokens(q_limpia)

    if not tokens:
        return []

    # --- FASE 1: Filtro en MongoDB ---
    # Construimos condiciones OR: si cualquier campo contiene
    # la query completa O cualquiera de los tokens, el documento pasa.
    condiciones = []
    campos = [
        "nombre", "descripcion", "texto_buscado_expandido",
        "referencia_limpia", "marca", "categoria"
    ]

    # Primero intentamos la query completa (más restrictivo, más relevante)
    for campo in campos:
        condiciones.append({campo: {"$regex": re.escape(q_limpia), "$options": "i"}})

    # Luego token por token (más amplio, captura coincidencias parciales)
    for token in tokens:
        for campo in campos:
            condiciones.append({campo: {"$regex": re.escape(token), "$options": "i"}})

    # Solo traemos los campos que necesitamos — menos datos = más rápido
    proyeccion = {
        "_id": 0,
        "codigo": 1,
        "nombre": 1,
        "marca": 1,
        "categoria": 1,
        "descripcion": 1,
        "texto_buscado_expandido": 1,
        "referencia_limpia": 1,
        "precio": 1,
    }

    try:
        candidatos = list(get_collection().find({"$or": condiciones}, proyeccion))
    except Exception as e:
        logger.error(f"Error MongoDB en buscar_productos: {e}")
        raise

    if not candidatos:
        return []

    # --- FASE 2: Re-ranking con RapidFuzz ---
    # Eliminamos duplicados (mismo codigo+nombre) y ordenamos por score
    vistos = set()
    resultados = []

    for doc in sorted(candidatos, key=lambda d: score_producto(q, d), reverse=True):
        clave = (doc.get("codigo"), doc.get("nombre"))
        if clave not in vistos:
            vistos.add(clave)
            doc["score"] = score_producto(q, doc)
            resultados.append(doc)

    return resultados[:limit]


# ============================================================
# FORMATO DE SALIDA
# ============================================================

def formatear_producto(p: dict) -> dict:
    """
    Normaliza la estructura de salida de cada producto.
    Todos los endpoints devuelven exactamente los mismos campos
    con los mismos nombres — consistencia para el frontend y para
    cualquier integración futura (WhatsApp, CRM, etc).
    """
    return {
        "codigo":      str(p.get("codigo", "")).strip(),
        "nombre":      str(p.get("nombre", "")).strip(),
        "marca":       str(p.get("marca", "")).strip(),
        "categoria":   str(p.get("categoria", "")).strip(),
        "descripcion": str(p.get("descripcion", "")).strip(),
        "referencia":  str(p.get("referencia_limpia", "")).strip(),
        "precio":      str(p.get("precio", "")).strip(),
    }