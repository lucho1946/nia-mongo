# ============================================================
# services/search.py
# Responsabilidad única: toda la lógica de búsqueda de productos.
# Tanto el router de productos como el de chat usan este mismo
# servicio — una sola fuente de verdad para buscar.
#
# VERSIÓN: 0.4
# CAMBIOS v0.4:
# - Umbral mínimo de relevancia (UMBRAL_MINIMO = 45.0)
# - Filtra resultados irrelevantes después de RapidFuzz
# - Evita que búsquedas multimodales devuelvan productos no relacionados
#
# VERSIÓN: 0.3
# CAMBIOS v0.3:
# - Detección de código VIA exacto (P123456, 123456)
# - buscar_por_codigo_exacto() con búsqueda directa por índice
# - Fallback a búsqueda normal si código no existe
# - EXISTENCIA agregado a proyecciones
#
# VERSIÓN: 0.2
# CAMBIOS v0.2:
# - Regla de negocio PV_FECHA: precio vigente solo si < 12 meses
# - Jerarquía completa NIVEL_0 al NIVEL_4 en respuesta
# - Stock por sede Bogotá y Cali con disponibilidad real
# - Equivalentes para ofrecer alternativas
# - Características técnicas incluidas en respuesta
# - Score de oportunidad comercial (preparado para Excel Don Andrés)
# - Búsqueda por texto_busqueda como campo principal
# - Filtro VISIBLE_EN_LINEA robusto para múltiples tipos de dato
#
# CAMPOS REALES EN MONGODB (vienen del ETL de SQL Server):
#   CODIGO, REFERENCIA, REF_ALTERNATIVA
#   DESCRIPCION_CORTA_PRE, DESCRIPCION_LARGA_PRE
#   MARCA_LET, PRECIO_VENTA, PV_FECHA
#   NIVEL_0, NIVEL_1, NIVEL_2, NIVEL_3, NIVEL_4
#   CARACTERISTICAS (array de pares titulo/valor)
#   APLICACIONES
#   STOCK_BOG, STOCK_CALI, STOCK_TOTAL
#   EQUIVALENTE, EQUIVALENTE_2
#   DIMENSION, PESO, VISIBLE_EN_LINEA
#   EXISTENCIA (tiempo estimado de entrega)
#   texto_busqueda (campo unificado construido por ETL)
#   score_oportunidad, tipo_sku (cuando llegue Excel de Don Andrés)
#
# REGLAS DE NEGOCIO:
# - Precio condicionado a PV_FECHA ≤ 12 meses (Andrés Valencia)
# - Solo productos con VISIBLE_EN_LINEA activo en búsqueda normal
# - Búsqueda por código exacto ignora VISIBLE_EN_LINEA
# - Jerarquía completa en respuesta para frontend y NIA
# - Stock real por sede para informar disponibilidad al cliente
# ============================================================

import re
import unicodedata
import logging
from datetime import datetime, timezone, timedelta
from rapidfuzz import fuzz
from .mongo import get_collection

logger = logging.getLogger(__name__)


# ============================================================
# PROYECCIÓN ESTÁNDAR
# Centralizada aquí para que buscar_productos y
# buscar_por_codigo_exacto usen exactamente los mismos campos.
# Si se agrega un campo nuevo solo se cambia aquí.
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
}


# ============================================================
# UMBRAL MÍNIMO DE RELEVANCIA
# Un score < 45 indica que el producto no tiene relación real
# con la búsqueda. Sin este filtro RapidFuzz acepta cualquier
# cosa que pase el regex de MongoDB, generando resultados
# irrelevantes especialmente en búsquedas multimodales.
#
# Valor calibrado empíricamente:
# - < 45: producto irrelevante (medidores cuando se busca compresor)
# - 45-65: coincidencia parcial aceptable
# - > 65: coincidencia fuerte
# - > 85: coincidencia muy precisa (código o referencia exacta)
# ============================================================
UMBRAL_MINIMO = 55.0


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def normalizar(texto: str) -> str:
    """
    Convierte cualquier texto a minúsculas, sin acentos y sin
    espacios dobles.
    Ejemplo: 'Válvula   Neumática' → 'valvula neumatica'
    Se aplica a la query del usuario y a los campos del producto
    antes de comparar — evita fallos por tildes o mayúsculas.
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
    Ejemplo: 'valvula neumatica 1/2' → ['valvula', 'neumatica', '1/2']
    Descarta tokens de menos de 2 caracteres y elimina duplicados
    manteniendo el orden original.
    """
    tokens = re.findall(r"[a-zA-Z0-9\-\.\/]+", normalizar(texto))
    return list(dict.fromkeys(t for t in tokens if len(t) >= 2))


# ============================================================
# DETECCIÓN DE CÓDIGO VIA
# ============================================================

def es_codigo_via(texto: str) -> bool:
    """
    Detecta si el texto parece un código de producto de VIA Industrial.

    Formatos válidos identificados en el catálogo real:
    - P123456     → P mayúscula + números (más común)
    - P123456A    → P + números + letras
    - 123456      → solo números de 6+ dígitos

    Esta detección permite que /chat busque por código exacto
    cuando el cliente escribe una referencia directa, en lugar
    de hacer búsqueda fuzzy que puede traer resultados incorrectos.

    NO detecta referencias como '22UN73' o 'CUT-C20' — esas
    se manejan correctamente con RapidFuzz en búsqueda normal.
    """
    texto = texto.strip()

    # Formato P + alfanumérico (ej: P123456, P123456A)
    if re.match(r'^P[0-9]{4,}[A-Za-z0-9]*$', texto, re.IGNORECASE):
        return True

    # Solo números de 6 o más dígitos (ej: 123456)
    if re.match(r'^\d{6,}$', texto):
        return True

    return False


# ============================================================
# BÚSQUEDA POR CÓDIGO EXACTO
# ============================================================

def buscar_por_codigo_exacto(codigo: str) -> list[dict]:
    """
    Búsqueda exacta por código de producto usando el índice CODIGO.
    Más rápida y precisa que RapidFuzz para códigos conocidos.

    NO filtra por VISIBLE_EN_LINEA — si el cliente o asesor
    escribe un código exacto, sabe lo que busca. Filtrar productos
    no visibles aquí podría confundir: el producto existe pero
    NIA dice que no lo encuentra.

    Retorna máximo 5 resultados para evitar duplicados en MongoDB.
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

def score_relevancia(q: str, doc: dict) -> float:
    """
    Calcula qué tan relevante es un producto para la búsqueda.
    Usa RapidFuzz — librería de similitud optimizada en C.

    CAMPOS USADOS PARA EL CÁLCULO:
    - texto_busqueda: campo unificado construido por el ETL con toda
      la información del producto concatenada. Es el campo principal.
    - DESCRIPCION_CORTA_PRE: nombre del producto — peso alto
    - REFERENCIA + REF_ALTERNATIVA: referencias técnicas — peso medio
    - score_oportunidad: relevancia comercial de VIA — bonus

    PESOS:
    - token_set_ratio en texto_busqueda (35%): ignora orden de palabras
    - partial_ratio en texto_busqueda (25%): detecta coincidencia parcial
    - token_sort_ratio en nombre (20%): compara nombre ordenando palabras
    - partial_ratio en referencias (15%): prioriza coincidencia exacta
    - bonus score_oportunidad (5%): productos más rentables primero
      (activo cuando llegue el Excel de Don Andrés)
    """
    qn = normalizar(q)

    texto_busqueda = normalizar(str(doc.get("texto_busqueda", "")))
    nombre         = normalizar(str(doc.get("DESCRIPCION_CORTA_PRE", "")))
    referencia     = normalizar(str(doc.get("REFERENCIA", "")))
    ref_alt        = normalizar(str(doc.get("REF_ALTERNATIVA", "")))

    s1 = fuzz.token_set_ratio(qn, texto_busqueda)
    s2 = fuzz.partial_ratio(qn, texto_busqueda)
    s3 = fuzz.token_sort_ratio(qn, nombre)
    s4 = max(
        fuzz.partial_ratio(qn, referencia),
        fuzz.partial_ratio(qn, ref_alt)
    )

    score_base = (s1 * 0.35) + (s2 * 0.25) + (s3 * 0.20) + (s4 * 0.15)

    # Bonus por score de oportunidad comercial
    # Normalizado a escala 0-5 para no distorsionar el score principal
    # Se activa cuando Don Andrés comparta el Excel con los scores
    try:
        score_op = float(doc.get("score_oportunidad") or 0)
        if score_op > 0:
            bonus = min(score_op / 100, 1.0) * 5
            score_base += bonus
    except (ValueError, TypeError):
        pass

    return round(score_base, 2)


# ============================================================
# BÚSQUEDA PRINCIPAL
# ============================================================

def buscar_productos(q: str, limit: int = 8) -> list[dict]:
    """
    Función principal de búsqueda. Recibe texto libre del usuario
    y retorna lista de productos ordenados por relevancia.

    DETECCIÓN DE CÓDIGO EXACTO:
    Si el texto parece un código VIA (P123456, 123456) busca
    directamente por código exacto usando el índice CODIGO.
    Si no encuentra → fallback a búsqueda normal.

    ESTRATEGIA EN DOS FASES (búsqueda normal):
    1. MongoDB filtra candidatos con regex — rápido
    2. RapidFuzz re-rankea — preciso

    FILTROS ACTIVOS:
    - VISIBLE_EN_LINEA: solo productos visibles al cliente
    - UMBRAL_MINIMO: descarta productos con score < 45
    """
    q_limpia = normalizar(q)
    tokens   = extraer_tokens(q_limpia)

    if not tokens:
        return []

    # -------------------------------------------------------
    # Detección de código exacto — búsqueda directa por índice
    # -------------------------------------------------------
    if es_codigo_via(q.strip()):
        logger.info(f"Código VIA detectado: {q.strip()} — búsqueda exacta")
        resultados_codigo = buscar_por_codigo_exacto(q.strip())
        if resultados_codigo:
            return resultados_codigo
        # Código no encontrado — continuar con búsqueda normal
        logger.info("Código no encontrado — fallback a búsqueda normal")

    # -------------------------------------------------------
    # FASE 1: Filtro en MongoDB con regex
    # -------------------------------------------------------
    condiciones_busqueda = []

    # Campos donde buscar — texto_busqueda primero por ser el más completo
    campos = [
        "texto_busqueda",
        "DESCRIPCION_CORTA_PRE",
        "DESCRIPCION_LARGA_PRE",
        "MARCA_LET",
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

    # Query completa primero — más restrictiva y precisa
    for campo in campos:
        condiciones_busqueda.append({
            campo: {"$regex": re.escape(q_limpia), "$options": "i"}
        })

    # Token por token — captura coincidencias parciales
    for token in tokens:
        for campo in campos:
            condiciones_busqueda.append({
                campo: {"$regex": re.escape(token), "$options": "i"}
            })

    # Filtro VISIBLE_EN_LINEA robusto — acepta True, 1, "1", "true"
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
        return []

    # -------------------------------------------------------
    # FASE 2: Re-ranking con RapidFuzz + score_oportunidad
    # Calculamos el score una sola vez por documento
    # -------------------------------------------------------
    scored = [
        (doc, score_relevancia(q, doc))
        for doc in candidatos
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # -------------------------------------------------------
    # FILTRO DE UMBRAL MÍNIMO
    # Descarta productos con score bajo que pasaron el regex
    # pero no tienen relación real con la búsqueda.
    # Crítico para búsquedas multimodales donde el query
    # puede ser muy específico (marca + modelo + referencia).
    # -------------------------------------------------------
    scored = [(doc, score) for doc, score in scored if score >= UMBRAL_MINIMO]

    if not scored:
        logger.info(f"Sin resultados por encima del umbral {UMBRAL_MINIMO} para: {q}")
        return []

    # Eliminar duplicados manteniendo el de mayor score
    vistos     = set()
    resultados = []

    for doc, score in scored:
        clave = (doc.get("CODIGO"), doc.get("DESCRIPCION_CORTA_PRE"))
        if clave not in vistos:
            vistos.add(clave)
            doc["_score_nia"] = score
            resultados.append(doc)

    return resultados[:limit]


# ============================================================
# FORMATO DE SALIDA
# ============================================================

def formatear_producto(p: dict) -> dict:
    """
    Normaliza la estructura de salida de cada producto.
    Es el contrato entre el backend y el frontend/NIA.
    Cualquier cambio aquí afecta toda la API.

    PRECIO — Regla de negocio (Andrés Valencia, Dirección General):
    Solo se muestra si PV_FECHA tiene menos de 12 meses.
    Si tiene más de 12 meses sin actualizar → "Consultarnos".
    Si no tiene fecha → "Consultarnos".

    STOCK — Disponibilidad real por sede:
    Se informa por Bogotá y Cali por separado.
    Si no hay stock en ninguna sede → "Consultar disponibilidad".

    TIEMPO DE ENTREGA:
    Viene del campo EXISTENCIA de SQL Server.
    Texto libre: "1 DIAS", "15 DIAS", "5 SEMANAS".
    Se muestra tal como viene de la base de datos.

    JERARQUÍA — 4 niveles completos:
    Permite al frontend mostrar la ubicación exacta del producto
    en el catálogo de VIA Industrial.

    CARACTERÍSTICAS TÉCNICAS:
    Array de pares título/valor para preguntas técnicas de NIA.

    EQUIVALENTES:
    Referencias alternativas cuando el producto no tiene stock.
    """

    # -------------------------------------------------------
    # 1. Validar vigencia del precio con PV_FECHA
    # -------------------------------------------------------
    precio_fmt = "Consultarnos"
    precio_raw = p.get("PRECIO_VENTA")
    pv_fecha   = p.get("PV_FECHA")

    if precio_raw and pv_fecha:
        try:
            if isinstance(pv_fecha, str):
                fecha_precio = datetime.fromisoformat(pv_fecha)
            else:
                fecha_precio = pv_fecha

            if fecha_precio.tzinfo is None:
                fecha_precio = fecha_precio.replace(tzinfo=timezone.utc)

            ahora         = datetime.now(timezone.utc)
            hace_12_meses = ahora - timedelta(days=365)

            if fecha_precio >= hace_12_meses:
                precio_fmt = f"${float(precio_raw):,.0f} COP"

        except (ValueError, TypeError):
            pass

    # -------------------------------------------------------
    # 2. Calcular disponibilidad de stock por sede
    # -------------------------------------------------------
    stock_bog   = float(p.get("STOCK_BOG")   or 0)
    stock_cali  = float(p.get("STOCK_CALI")  or 0)
    stock_total = float(p.get("STOCK_TOTAL") or 0)

    if stock_bog > 0 or stock_cali > 0:
        sedes = []
        if stock_bog  > 0: sedes.append(f"Bogotá ({int(stock_bog)} und)")
        if stock_cali > 0: sedes.append(f"Cali ({int(stock_cali)} und)")
        disponibilidad = f"Disponible en {', '.join(sedes)}"
    elif stock_total > 0:
        disponibilidad = f"Disponible ({int(stock_total)} und)"
    else:
        disponibilidad = "Consultar disponibilidad"

    # -------------------------------------------------------
    # 3. Características técnicas — array de pares título/valor
    # -------------------------------------------------------
    caracteristicas = p.get("CARACTERISTICAS", [])
    if not isinstance(caracteristicas, list):
        caracteristicas = []

    # -------------------------------------------------------
    # 4. Score de oportunidad — seguro contra None
    # -------------------------------------------------------
    score_op = None
    try:
        raw_score = p.get("score_oportunidad")
        if raw_score is not None:
            score_op = float(raw_score)
    except (ValueError, TypeError):
        pass

    return {
        # Identificación
        "codigo":          str(p.get("CODIGO",          "")).strip(),
        "referencia":      str(p.get("REFERENCIA",      "")).strip(),
        "ref_alternativa": str(p.get("REF_ALTERNATIVA", "")).strip(),

        # Descripción
        "nombre":      str(p.get("DESCRIPCION_CORTA_PRE", "")).strip(),
        "descripcion": str(p.get("DESCRIPCION_LARGA_PRE", "")).strip()[:300],
        "marca":       str(p.get("MARCA_LET",             "")).strip(),

        # Jerarquía completa VIA Industrial
        "nivel_0": str(p.get("NIVEL_0", "")).strip(),
        "nivel_1": str(p.get("NIVEL_1", "")).strip(),
        "nivel_2": str(p.get("NIVEL_2", "")).strip(),
        "nivel_3": str(p.get("NIVEL_3", "")).strip(),
        "nivel_4": str(p.get("NIVEL_4", "")).strip(),

        # Comercial
        "precio":          precio_fmt,
        "disponibilidad":  disponibilidad,
        "tiempo_entrega":  str(p.get("EXISTENCIA", "")).strip(),

        # Técnico
        "caracteristicas": caracteristicas,
        "aplicaciones":    str(p.get("APLICACIONES", "")).strip(),

        # Equivalentes
        "equivalente":   str(p.get("EQUIVALENTE",   "")).strip(),
        "equivalente_2": str(p.get("EQUIVALENTE_2", "")).strip(),

        # Físico
        "dimension": str(p.get("DIMENSION", "")).strip(),
        "peso":      float(p.get("PESO") or 0) if p.get("PESO") else None,

        # Score comercial — activo cuando llegue Excel de Don Andrés
        "score_oportunidad": score_op,
        "tipo_sku":          str(p.get("tipo_sku", "")).strip(),
    }