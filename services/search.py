# ============================================================
# services/search.py
# ============================================================
# Responsabilidad única:
# Toda la lógica de búsqueda de productos.
#
# Tanto el router de productos como el chat usan este mismo servicio:
# una sola fuente de verdad para buscar productos reales.
#
# VERSIÓN: 1.0
#
# CAMBIOS v1.0:
# - El ranking deja de depender de familias manuales.
# - La prioridad de búsqueda se basa en la jerarquía real del catálogo:
#   NIVEL_0, NIVEL_1, NIVEL_2, NIVEL_3, NIVEL_4.
# - DESCRIPCION_CORTA_PRE pesa más que DESCRIPCION_LARGA_PRE.
# - DESCRIPCION_LARGA_PRE ayuda, pero no domina la identidad del producto.
# - Accesorios/repuestos se penalizan desde catalog_line_matcher cuando
#   el cliente no los pidió explícitamente.
#
# REGLAS DE NEGOCIO:
# - products_catalog = fuente de verdad de productos reales.
# - score_nia = prioridad comercial, no reemplaza compatibilidad.
# - Precio condicionado a PV_FECHA ≤ 12 meses.
# - Solo productos con VISIBLE_EN_LINEA activo en búsqueda normal.
# - Búsqueda por código exacto ignora VISIBLE_EN_LINEA.
# - NIA debe preferir no recomendar antes que recomendar incompatible.
# ============================================================

import json
import re
import unicodedata
import logging
from datetime import datetime, timezone, timedelta

from rapidfuzz import fuzz

from .mongo import get_collection
from .catalog_line_matcher import evaluate_catalog_line_match

logger = logging.getLogger(__name__)


# ============================================================
# PROYECCIÓN ESTÁNDAR
# ============================================================

PROYECCION_PRODUCTO = {
    "_id":                   0,
    "CODIGO":                1,
    "REFERENCIA":            1,
    "REF_ALTERNATIVA":       1,
    "MARCA_LET":             1,
    "DESCRIPCION_CORTA_PRE": 1,
    "DESCRIPCION_LARGA_PRE": 1,
    "PRECIO_VENTA":          1,
    "PV_FECHA":              1,
    "NIVEL_0":               1,
    "NIVEL_1":               1,
    "NIVEL_2":               1,
    "NIVEL_3":               1,
    "NIVEL_4":               1,
    "CARACTERISTICAS":       1,
    "APLICACIONES":          1,
    "STOCK_BOG":             1,
    "STOCK_CALI":            1,
    "STOCK_TOTAL":           1,
    "EQUIVALENTE":           1,
    "EQUIVALENTE_2":         1,
    "DIMENSION":             1,
    "PESO":                  1,
    "VISIBLE_EN_LINEA":      1,
    "EXISTENCIA":            1,
    "texto_busqueda":        1,
    "score_oportunidad":     1,
    "tipo_sku":              1,

    # Scoring comercial aplicado desde Excel de Don Andrés.
    "score_nia":             1,
    "score_source":          1,
    "score_version":         1,
    "score_updated_at":      1,
}


# ============================================================
# UMBRAL MÍNIMO DE RELEVANCIA
# ============================================================

UMBRAL_MINIMO = 60.0


# ============================================================
# CONFIGURACIÓN DE SCORE COMERCIAL
# ============================================================
# score_nia NO debe dominar la búsqueda.
# Sirve para ordenar mejor productos ya relevantes.
# ============================================================

MAX_BONUS_SCORE_NIA = 12.0


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def normalizar(texto: str) -> str:
    """
    Convierte cualquier texto a minúsculas, sin acentos y sin
    espacios dobles.
    """
    texto = str(texto).lower().strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", texto)


def extraer_tokens(texto: str) -> list[str]:
    """
    Divide el texto en palabras clave individuales.
    """
    tokens = re.findall(r"[a-zA-Z0-9\-\.\/]+", normalizar(texto))
    return list(dict.fromkeys(t for t in tokens if len(t) >= 2))


def _safe_float(value, default: float = 0.0) -> float:
    """
    Convierte valores numéricos de MongoDB a float seguro.
    """
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def _texto_principal_doc(doc: dict) -> str:
    """
    Texto principal del producto para evaluar identidad.

    Importante:
    No usamos DESCRIPCION_LARGA_PRE aquí porque puede contener usos,
    aplicaciones o componentes internos que confunden la identidad real.
    """
    partes = [
        doc.get("DESCRIPCION_CORTA_PRE", ""),
        doc.get("NIVEL_0", ""),
        doc.get("NIVEL_1", ""),
        doc.get("NIVEL_2", ""),
        doc.get("NIVEL_3", ""),
        doc.get("NIVEL_4", ""),
        doc.get("REFERENCIA", ""),
        doc.get("REF_ALTERNATIVA", ""),
    ]

    return normalizar(" ".join(str(p) for p in partes if p))


# ============================================================
# BONUSES Y AJUSTES DE RANKING
# ============================================================

def _bonus_por_coincidencias(qn: str, doc: dict, tokens: list[str]) -> float:
    """
    Calcula bonus adicional por coincidencias útiles.
    """
    nombre = normalizar(str(doc.get("DESCRIPCION_CORTA_PRE", "")))
    referencias = normalizar(
        f"{doc.get('REFERENCIA', '')} {doc.get('REF_ALTERNATIVA', '')}"
    )
    categorias = normalizar(
        f"{doc.get('NIVEL_0', '')} {doc.get('NIVEL_1', '')} "
        f"{doc.get('NIVEL_2', '')} {doc.get('NIVEL_3', '')} {doc.get('NIVEL_4', '')}"
    )
    texto_busqueda = normalizar(str(doc.get("texto_busqueda", "")))

    bonus = 0.0

    if qn and qn in nombre:
        bonus += 8.0
    if qn and qn in referencias:
        bonus += 10.0
    if qn and qn in categorias:
        bonus += 6.0
    if qn and qn in texto_busqueda:
        bonus += 6.0

    bonus_tokens = 0.0

    for token in tokens:
        if token in nombre:
            bonus_tokens += 3.0
        if token in referencias:
            bonus_tokens += 5.0
        if token in categorias:
            bonus_tokens += 2.0
        if token in texto_busqueda:
            bonus_tokens += 1.0

    bonus += min(bonus_tokens, 15.0)

    return bonus

def _bonus_score_oportunidad(doc: dict) -> float:
    """
    Bonus histórico por score_oportunidad, si existe.
    Se mantiene por compatibilidad.
    """
    score_op = _safe_float(doc.get("score_oportunidad"), 0.0)

    if score_op <= 0:
        return 0.0

    return min(score_op / 100, 1.0) * 5.0


def _bonus_score_nia(doc: dict) -> float:
    """
    Bonus comercial basado en score_nia.

    Regla:
    - score_nia viene del Excel de Don Andrés.
    - No reemplaza relevancia técnica.
    - Solo suma hasta MAX_BONUS_SCORE_NIA puntos.
    - Si no existe o es 0, no afecta.
    """
    score_nia = _safe_float(doc.get("score_nia"), 0.0)

    if score_nia <= 0:
        return 0.0

    normalized = min(score_nia, 100.0) / 100.0

    return normalized * MAX_BONUS_SCORE_NIA


# ============================================================
# DETECCIÓN DE CÓDIGO VIA
# ============================================================

def es_codigo_via(texto: str) -> bool:
    """
    Detecta si el texto parece un código de producto VIA.
    """
    texto = texto.strip()

    if re.match(r'^P[0-9]{4,}[A-Za-z0-9]*$', texto, re.IGNORECASE):
        return True

    if re.match(r'^\d{6,}$', texto):
        return True

    return False


# ============================================================
# BÚSQUEDA POR CÓDIGO EXACTO
# ============================================================

def buscar_por_codigo_exacto(codigo: str) -> list[dict]:
    """
    Búsqueda exacta por código de producto usando índice CODIGO.
    """
    try:
        resultados = list(get_collection().find(
            {"CODIGO": {"$regex": f"^{re.escape(codigo)}$", "$options": "i"}},
            PROYECCION_PRODUCTO
        ).limit(5))
        return resultados

    except Exception as e:
        logger.error(f"Error en buscar_por_codigo_exacto: {e}")
        return []


# ============================================================
# SCORING DE RELEVANCIA
# ============================================================

def evaluar_relevancia(q: str, doc: dict) -> dict:
    """
    Devuelve el detalle completo del scoring de un producto.

    Nueva estrategia:
    - No usa familias manuales.
    - No usa listas manuales de marcas.
    - Prioriza jerarquía real del catálogo:
      NIVEL_0, NIVEL_1, NIVEL_2, NIVEL_3, NIVEL_4.
    - Prioriza DESCRIPCION_CORTA_PRE sobre DESCRIPCION_LARGA_PRE.
    - Usa MARCA_LET directamente desde catalog_line_matcher.
    - Mantiene referencia, texto_busqueda y score_nia.
    - Penaliza accesorios/repuestos desde catalog_line_matcher cuando
      el cliente no los pidió explícitamente.

    Esta función usa catalog_line_matcher como criterio principal de relevancia.
    """
    qn = normalizar(q)

    texto_busqueda = normalizar(str(doc.get("texto_busqueda", "")))
    nombre = normalizar(str(doc.get("DESCRIPCION_CORTA_PRE", "")))
    referencia = normalizar(str(doc.get("REFERENCIA", "")))
    ref_alt = normalizar(str(doc.get("REF_ALTERNATIVA", "")))

    # --------------------------------------------------------
    # Score textual base legacy-controlado
    # --------------------------------------------------------
    # Se mantiene para compatibilidad con RapidFuzz, pero deja de
    # ser el centro de decisión. El nuevo centro es catalog_line_match.
    # --------------------------------------------------------
    s1 = fuzz.token_set_ratio(qn, texto_busqueda)
    s2 = fuzz.partial_ratio(qn, texto_busqueda)
    s3 = fuzz.token_sort_ratio(qn, nombre)
    s4 = max(
        fuzz.partial_ratio(qn, referencia),
        fuzz.partial_ratio(qn, ref_alt)
    )

    score_textual = (s1 * 0.25) + (s2 * 0.20) + (s3 * 0.25) + (s4 * 0.20)

    # --------------------------------------------------------
    # Nuevo matcher por líneas reales del catálogo.
    # --------------------------------------------------------
    # Este matcher evalúa:
    # - NIVEL_0 a NIVEL_4
    # - DESCRIPCION_CORTA_PRE
    # - DESCRIPCION_LARGA_PRE
    # - REFERENCIA / REF_ALTERNATIVA / CODIGO
    # - MARCA_LET
    #
    # Importante:
    # MARCA_LET se evalúa desde el campo real del producto,
    # no desde una lista manual de marcas.
    # --------------------------------------------------------
    catalog_line_match = evaluate_catalog_line_match(qn, doc)
    catalog_line_score = catalog_line_match.get("score", 0.0)

    # --------------------------------------------------------
    # Bonus comercial.
    # --------------------------------------------------------
    bonus_oportunidad = _bonus_score_oportunidad(doc)
    bonus_score_nia = _bonus_score_nia(doc)

    # --------------------------------------------------------
    # Score final.
    # --------------------------------------------------------
    # La coherencia ahora viene de:
    # - NIVEL_0 a NIVEL_4
    # - DESCRIPCION_CORTA_PRE
    # - DESCRIPCION_LARGA_PRE con peso menor
    # - MARCA_LET real del catálogo
    # - identidad principal del producto
    # --------------------------------------------------------
    score_total = max(
        score_textual
        + catalog_line_score
        + bonus_oportunidad
        + bonus_score_nia,
        0.0
    )

    score_nia_raw = _safe_float(doc.get("score_nia"), 0.0)

    return {
        "score_total": round(score_total, 2),
        "score_textual": round(score_textual, 2),

        # Nuevo debug principal.
        "catalog_line_score": round(catalog_line_score, 2),
        "line_score": catalog_line_match.get("line_score", 0.0),
        "description_short_score": catalog_line_match.get("description_short_score", 0.0),
        "description_long_score": catalog_line_match.get("description_long_score", 0.0),
        "reference_score": catalog_line_match.get("reference_score", 0.0),
        "brand_score": catalog_line_match.get("brand_score", 0.0),
        "text_search_score": catalog_line_match.get("text_search_score", 0.0),
        "token_bonus": catalog_line_match.get("token_bonus", 0.0),
        "secondary_penalty": catalog_line_match.get("secondary_penalty", 0.0),
        "matched_levels": catalog_line_match.get("matched_levels", []),
        "matched_fields": catalog_line_match.get("matched_fields", []),

        # Campos legacy mantenidos temporalmente para compatibilidad.
        # Ya no participan en el cálculo de score_total.
        "bonus_marca": 0.0,
        "ajuste_marca": 0.0,
        "bonus_marca_familia": 0.0,
        "ajuste_familia": 0.0,
        "ajuste_secundario": 0.0,
        "ajuste_incompatibilidad": 0.0,

        # Comercial.
        "bonus_oportunidad": round(bonus_oportunidad, 2),
        "score_nia_raw": round(score_nia_raw, 4),
        "bonus_score_nia": round(bonus_score_nia, 2),

        # Debug textual legacy.
        "s1_token_set": round(s1, 2),
        "s2_partial_texto": round(s2, 2),
        "s3_token_sort_nombre": round(s3, 2),
        "s4_referencia": round(s4, 2),
    }


def score_relevancia(q: str, doc: dict) -> float:
    """
    Mantiene compatibilidad con el código anterior.
    """
    return evaluar_relevancia(q, doc)["score_total"]


# ============================================================
# BÚSQUEDA PRINCIPAL
# ============================================================

def buscar_productos(mensaje: str, limit: int = 8) -> list[dict]:
    """
    Función principal de búsqueda.

    Estrategia:
    1. MongoDB filtra candidatos con regex.
    2. RapidFuzz + reglas industriales reordenan.
    3. score_nia suma prioridad comercial controlada.
    """
    q_limpia = normalizar(mensaje)
    tokens = extraer_tokens(q_limpia)

    if not tokens:
        return []

    # -------------------------------------------------------
    # Detección de código exacto
    # -------------------------------------------------------
    if es_codigo_via(mensaje.strip()):
        logger.info(f"Código VIA detectado: {mensaje.strip()} — búsqueda exacta")
        resultados_codigo = buscar_por_codigo_exacto(mensaje.strip())
        if resultados_codigo:
            return resultados_codigo
        logger.info("Código no encontrado — fallback a búsqueda normal")

    # -------------------------------------------------------
    # FASE 1: Filtro en MongoDB con regex
    # -------------------------------------------------------
    condiciones_busqueda = []

    campos = [
        "texto_busqueda",
        "DESCRIPCION_CORTA_PRE",
        "DESCRIPCION_LARGA_PRE",
        "MARCA_LET",
        "NIVEL_0",
        "NIVEL_1",
        "NIVEL_2",
        "NIVEL_3",
        "NIVEL_4",
        "REFERENCIA",
        "REF_ALTERNATIVA",
        "CODIGO",
        "APLICACIONES",
        "EQUIVALENTE",
        "EQUIVALENTE_2",
    ]

    for campo in campos:
        condiciones_busqueda.append({
            campo: {"$regex": re.escape(q_limpia), "$options": "i"}
        })

    for token in tokens:
        for campo in campos:
            condiciones_busqueda.append({
                campo: {"$regex": re.escape(token), "$options": "i"}
            })

    filtro_visible = {
        "VISIBLE_EN_LINEA": {"$in": [True, 1, "1", "true", "True"]}
    }

    try:
        candidatos = list(get_collection().find(
            {
                "$and": [
                    {"$or": condiciones_busqueda},
                    filtro_visible
                ]
            },
            PROYECCION_PRODUCTO
        ))

    except Exception as e:
        logger.error(f"Error MongoDB en buscar_productos: {e}")
        raise

    if not candidatos:
        logger.info(
            "[SEARCH_TRACE] %s",
            json.dumps({
                "query": mensaje,
                "total_candidatos": 0,
                "total_finales": 0,
                "umbral": UMBRAL_MINIMO,
                "top_resultados": []
            }, ensure_ascii=False, default=str)
        )
        return []

    # -------------------------------------------------------
    # FASE 2: Re-ranking
    # -------------------------------------------------------
    scored = []

    for doc in candidatos:
        detalle = evaluar_relevancia(mensaje, doc)
        doc["_score_nia"] = detalle["score_total"]
        doc["_score_debug"] = detalle
        scored.append((doc, detalle))

    scored.sort(key=lambda x: x[1]["score_total"], reverse=True)

    # -------------------------------------------------------
    # FILTRO DE UMBRAL MÍNIMO
    # -------------------------------------------------------
    scored = [
        (doc, detalle)
        for doc, detalle in scored
        if detalle["score_total"] >= UMBRAL_MINIMO
    ]

    if not scored:
        logger.info(f"Sin resultados por encima del umbral {UMBRAL_MINIMO} para: {mensaje}")
        logger.info(
            "[SEARCH_TRACE] %s",
            json.dumps({
                "query": mensaje,
                "total_candidatos": len(candidatos),
                "total_finales": 0,
                "umbral": UMBRAL_MINIMO,
                "top_resultados": []
            }, ensure_ascii=False, default=str)
        )
        return []

    # -------------------------------------------------------
    # Eliminar duplicados manteniendo mayor score
    # -------------------------------------------------------
    vistos = set()
    resultados = []

    for doc, detalle in scored:
        clave = (doc.get("CODIGO"), doc.get("DESCRIPCION_CORTA_PRE"))

        if clave not in vistos:
            vistos.add(clave)
            doc["_score_nia"] = detalle["score_total"]
            doc["_score_debug"] = detalle
            resultados.append(doc)

    # -------------------------------------------------------
    # LOG DE TRAZABILIDAD DEL RANKING
    # -------------------------------------------------------
    top_debug = []

    for doc in resultados[:5]:
        debug = doc.get("_score_debug", {})

    top_debug.append({
        "codigo": doc.get("CODIGO", ""),
        "nombre": doc.get("DESCRIPCION_CORTA_PRE", ""),
        "marca": doc.get("MARCA_LET", ""),
        "nivel_0": doc.get("NIVEL_0", ""),
        "nivel_1": doc.get("NIVEL_1", ""),
        "nivel_2": doc.get("NIVEL_2", ""),
        "nivel_3": doc.get("NIVEL_3", ""),
        "nivel_4": doc.get("NIVEL_4", ""),

        "score_total": debug.get("score_total"),
        "score_textual": debug.get("score_textual"),

        # Nuevo ranking por líneas.
        "catalog_line_score": debug.get("catalog_line_score"),
        "line_score": debug.get("line_score"),
        "description_short_score": debug.get("description_short_score"),
        "description_long_score": debug.get("description_long_score"),
        "reference_score": debug.get("reference_score"),
        "matched_levels": debug.get("matched_levels"),
        "matched_fields": debug.get("matched_fields"),

        # Marca y comercial.
        "bonus_marca": debug.get("bonus_marca"),
        "ajuste_marca": debug.get("ajuste_marca"),
        "bonus_oportunidad": debug.get("bonus_oportunidad"),
        "score_nia_raw": debug.get("score_nia_raw"),
        "bonus_score_nia": debug.get("bonus_score_nia"),
        "score_source": doc.get("score_source"),
        "score_version": doc.get("score_version"),
    })

    logger.info(
        "[SEARCH_TRACE] %s",
        json.dumps({
            "query": mensaje,
            "total_candidatos": len(candidatos),
            "total_finales": len(resultados),
            "umbral": UMBRAL_MINIMO,
            "max_bonus_score_nia": MAX_BONUS_SCORE_NIA,
            "top_resultados": top_debug,
        }, ensure_ascii=False, default=str)
    )

    return resultados[:limit]


# ============================================================
# FORMATO DE SALIDA
# ============================================================

def formatear_producto(p: dict) -> dict:
    """
    Normaliza la estructura de salida de cada producto.
    Es el contrato entre backend, frontend y NIA.
    """

    # -------------------------------------------------------
    # 1. Validar vigencia del precio con PV_FECHA
    # -------------------------------------------------------
    precio_fmt = "Consultarnos"
    precio_raw = p.get("PRECIO_VENTA")
    pv_fecha = p.get("PV_FECHA")

    if precio_raw and pv_fecha:
        try:
            if isinstance(pv_fecha, str):
                fecha_precio = datetime.fromisoformat(pv_fecha)
            else:
                fecha_precio = pv_fecha

            if fecha_precio.tzinfo is None:
                fecha_precio = fecha_precio.replace(tzinfo=timezone.utc)

            ahora = datetime.now(timezone.utc)
            hace_12_meses = ahora - timedelta(days=365)

            if fecha_precio >= hace_12_meses:
                precio_fmt = f"${float(precio_raw):,.0f} COP"

        except (ValueError, TypeError):
            pass

    # -------------------------------------------------------
    # 2. Calcular disponibilidad de stock por sede
    # -------------------------------------------------------
    stock_bog = _safe_float(p.get("STOCK_BOG"), 0.0)
    stock_cali = _safe_float(p.get("STOCK_CALI"), 0.0)
    stock_total = _safe_float(p.get("STOCK_TOTAL"), 0.0)

    if stock_bog > 0 or stock_cali > 0:
        sedes = []

        if stock_bog > 0:
            sedes.append(f"Bogotá ({int(stock_bog)} und)")

        if stock_cali > 0:
            sedes.append(f"Cali ({int(stock_cali)} und)")

        disponibilidad = f"Disponible en {', '.join(sedes)}"

    elif stock_total > 0:
        disponibilidad = f"Disponible ({int(stock_total)} und)"

    else:
        disponibilidad = "Consultar disponibilidad"

    # -------------------------------------------------------
    # 3. Características técnicas
    # -------------------------------------------------------
    caracteristicas = p.get("CARACTERISTICAS", [])

    if not isinstance(caracteristicas, list):
        caracteristicas = []

    # -------------------------------------------------------
    # 4. Scores
    # -------------------------------------------------------
    score_op = None
    raw_score_op = p.get("score_oportunidad")

    if raw_score_op is not None:
        try:
            score_op = float(raw_score_op)
        except (ValueError, TypeError):
            score_op = None

    score_nia = None
    raw_score_nia = p.get("score_nia")

    if raw_score_nia is not None:
        try:
            score_nia = float(raw_score_nia)
        except (ValueError, TypeError):
            score_nia = None

    return {
        # Identificación
        "codigo":          str(p.get("CODIGO", "")).strip(),
        "referencia":      str(p.get("REFERENCIA", "")).strip(),
        "ref_alternativa": str(p.get("REF_ALTERNATIVA", "")).strip(),

        # Descripción
        "nombre":      str(p.get("DESCRIPCION_CORTA_PRE", "")).strip(),
        "descripcion": str(p.get("DESCRIPCION_LARGA_PRE", "")).strip()[:300],
        "marca":       str(p.get("MARCA_LET", "")).strip(),

        # Jerarquía VIA Industrial
        "nivel_0": str(p.get("NIVEL_0", "")).strip(),
        "nivel_1": str(p.get("NIVEL_1", "")).strip(),
        "nivel_2": str(p.get("NIVEL_2", "")).strip(),
        "nivel_3": str(p.get("NIVEL_3", "")).strip(),
        "nivel_4": str(p.get("NIVEL_4", "")).strip(),

        # Comercial
        "precio":         precio_fmt,
        "disponibilidad": disponibilidad,
        "tiempo_entrega": str(p.get("EXISTENCIA", "")).strip(),

        # Técnico
        "caracteristicas": caracteristicas,
        "aplicaciones":    str(p.get("APLICACIONES", "")).strip(),

        # Equivalentes
        "equivalente":   str(p.get("EQUIVALENTE", "")).strip(),
        "equivalente_2": str(p.get("EQUIVALENTE_2", "")).strip(),

        # Físico
        "dimension": str(p.get("DIMENSION", "")).strip(),
        "peso":      float(p.get("PESO") or 0) if p.get("PESO") else None,

        # Scores
        "score_oportunidad": score_op,
        "tipo_sku":          str(p.get("tipo_sku", "")).strip(),

        # Score comercial de Don Andrés
        "score_nia":         score_nia,
        "score_source":      str(p.get("score_source", "")).strip(),
        "score_version":     str(p.get("score_version", "")).strip(),

        # Debug interno útil para pruebas.
        "_score_nia":        p.get("_score_nia"),
        "_score_debug":      p.get("_score_debug"),
    }