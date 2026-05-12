# ============================================================
# services/search.py
# Responsabilidad única: toda la lógica de búsqueda de productos.
# Tanto el router de productos como el de chat usan este mismo
# servicio — una sola fuente de verdad para buscar.
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
#   texto_busqueda (campo unificado construido por ETL)
#   score_oportunidad, tipo_sku (cuando llegue Excel de Don Andrés)
#
# REGLAS DE NEGOCIO:
# - Precio condicionado a PV_FECHA ≤ 12 meses (Andrés Valencia)
# - Solo productos con VISIBLE_EN_LINEA activo
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
    # Toma el mejor score entre referencia principal y alternativa
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

    ESTRATEGIA EN DOS FASES:
    1. MongoDB filtra candidatos con regex — rápido, reduce de 287k a
       un conjunto manejable usando los índices disponibles
    2. RapidFuzz re-rankea los candidatos — preciso pero costoso,
       por eso se aplica solo al conjunto filtrado, no a toda la colección

    FILTROS ACTIVOS:
    - VISIBLE_EN_LINEA: solo productos visibles al cliente
      (robusto para booleano, entero 0/1 y string)

    CAMPOS DE BÚSQUEDA:
    Incluye texto_busqueda como campo principal (concentra toda
    la información del producto) más campos individuales para
    mayor cobertura en búsquedas específicas.
    """
    q_limpia = normalizar(q)
    tokens   = extraer_tokens(q_limpia)

    if not tokens:
        return []

    # --- FASE 1: Filtro en MongoDB ---
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
    # porque MongoDB puede tener el campo en diferentes formatos
    filtro_visible = {
        "VISIBLE_EN_LINEA": {"$in": [True, 1, "1", "true", "True"]}
    }

    # Proyección — todos los campos que NIA necesita
    proyeccion = {
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
        "texto_busqueda":        1,
        "score_oportunidad":     1,
        "tipo_sku":              1,
        "EXISTENCIA": 1,
    }

    try:
        candidatos = list(get_collection().find(
            {
                "$and": [
                    {"$or": condiciones_busqueda},
                    filtro_visible
                ]
            },
            proyeccion
        ))
    except Exception as e:
        logger.error(f"Error MongoDB en buscar_productos: {e}")
        raise

    if not candidatos:
        return []

    # --- FASE 2: Re-ranking con RapidFuzz + score_oportunidad ---
    # Calculamos el score una sola vez por documento para no duplicar cómputo
    scored = [
        (doc, score_relevancia(q, doc))
        for doc in candidatos
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

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

    JERARQUÍA — 4 niveles completos:
    Permite al frontend mostrar la ubicación exacta del producto
    en el catálogo de VIA Industrial.

    CARACTERÍSTICAS TÉCNICAS:
    Array de pares título/valor para que NIA pueda responder
    preguntas técnicas específicas del cliente.

    EQUIVALENTES:
    Referencias alternativas para que NIA ofrezca opciones
    cuando el producto principal no está disponible.
    """

    # -------------------------------------------------------
    # 1. Validar vigencia del precio con PV_FECHA
    # -------------------------------------------------------
    precio_fmt = "Consultarnos"
    precio_raw = p.get("PRECIO_VENTA")
    pv_fecha   = p.get("PV_FECHA")

    if precio_raw and pv_fecha:
        try:
            # PV_FECHA viene como string ISO desde MongoDB
            if isinstance(pv_fecha, str):
                fecha_precio = datetime.fromisoformat(pv_fecha)
            else:
                fecha_precio = pv_fecha

            # Asegurar timezone UTC para comparar correctamente
            if fecha_precio.tzinfo is None:
                fecha_precio = fecha_precio.replace(tzinfo=timezone.utc)

            ahora         = datetime.now(timezone.utc)
            hace_12_meses = ahora - timedelta(days=365)

            if fecha_precio >= hace_12_meses:
                precio_fmt = f"${float(precio_raw):,.0f} COP"
            # else: se mantiene "Consultarnos"

        except (ValueError, TypeError):
            pass  # Se mantiene "Consultarnos"

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

        # Jerarquía completa de categorías VIA Industrial
        # Categoría → Línea → Sublínea → Producto
        "nivel_0": str(p.get("NIVEL_0", "")).strip(),
        "nivel_1": str(p.get("NIVEL_1", "")).strip(),
        "nivel_2": str(p.get("NIVEL_2", "")).strip(),
        "nivel_3": str(p.get("NIVEL_3", "")).strip(),
        "nivel_4": str(p.get("NIVEL_4", "")).strip(),

        # Comercial
        "precio":         precio_fmt,
        "disponibilidad": disponibilidad,
        # Campo EXISTENCIA de SQL Server — tiempo estimado de entrega
        "tiempo_entrega": str(p.get("EXISTENCIA", "")).strip(),

        # Características técnicas estructuradas
        # Ejemplo: [{"titulo": "Voltaje", "valor": "220V"}]
        "caracteristicas": caracteristicas,

        # Aplicaciones del producto
        "aplicaciones": str(p.get("APLICACIONES", "")).strip(),

        # Equivalentes para ofrecer alternativas al cliente
        "equivalente":   str(p.get("EQUIVALENTE",   "")).strip(),
        "equivalente_2": str(p.get("EQUIVALENTE_2", "")).strip(),

        # Físico
        "dimension": str(p.get("DIMENSION", "")).strip(),
        "peso":       float(p.get("PESO") or 0) if p.get("PESO") else None,

        # Score comercial de VIA Industrial
        # Disponible cuando Don Andrés comparta el Excel del scoring
        "score_oportunidad": score_op,
        "tipo_sku":          str(p.get("tipo_sku", "")).strip(),
    }