# ============================================================
# services/search.py
# Responsabilidad única: toda la lógica de búsqueda de productos.
# Tanto el router de productos como el de chat usan este mismo
# servicio — una sola fuente de verdad para buscar.
#
# VERSIÓN: 0.6
# CAMBIOS v0.6:
# - Observabilidad del ranking con logs SEARCH_TRACE
# - score_relevancia() respaldado por evaluación detallada
# - Se registra score total, score textual, bonus, penalizaciones
# - Penalización fina para accesorios, repuestos y controladores
#   cuando la búsqueda apunta a un equipo principal
# - Se mantiene la interfaz pública de búsqueda y formato
# - Mejor priorización por familias industriales
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

import json
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
# Un score < 60 indica que el producto no tiene relación real
# con la búsqueda. Sin este filtro RapidFuzz acepta cualquier
# cosa que pase el regex de MongoDB, generando resultados
# irrelevantes especialmente en búsquedas multimodales.
# ============================================================
UMBRAL_MINIMO = 60.0


# ============================================================
# FAMILIAS INDUSTRIALES
# Estas familias ayudan a distinguir el tipo de producto real.
# La idea es evitar que una búsqueda de "válvula" termine
# devolviendo una bomba solo porque ambas comparten "neumática".
# ============================================================

FAMILY_KEYWORDS = {
    "valvula": [
        "valvula", "valvulas", "electrovalvula", "electrovalvulas",
        "solenoide", "solenoides", "valve"
    ],
    "bomba": [
        "bomba", "bombas"
    ],
    "compresor": [
        "compresor", "compresores"
    ],
    "sensor": [
        "sensor", "sensores", "transmisor", "transmisores", "sonda", "sondas"
    ],
    "manometro": [
        "manometro", "manometros", "vacuometro", "vacuometros",
        "presostato", "presostatos"
    ],
    "medicion": [
        "medidor", "medidores", "indicador", "indicadores", "contador", "contadores"
    ],
    "regulador": [
        "regulador", "reguladores", "reductor", "reductores"
    ],
    "filtro": [
        "filtro", "filtros"
    ],
    "cilindro": [
        "cilindro", "cilindros", "actuador", "actuadores"
    ],
    "motor": [
        "motor", "motores"
    ],
    "caudal": [
        "caudal", "caudalimetro", "caudalimetros", "flowmeter"
    ],
    "temperatura": [
        "temperatura", "termometro", "termometros", "termostato",
        "termostatos", "termocupla", "termocuplas", "rtd"
    ],
    "presion": [
        "presion", "pressure"
    ],
}


# ============================================================
# TIPOS SECUNDARIOS
# Estos términos no suelen ser el producto principal buscado.
# Sirven para penalizar resultados que son accesorios,
# repuestos o controladores cuando el cliente busca un equipo base.
# ============================================================

SECONDARY_KEYWORDS = {
    "accesorio": [
        "accesorio", "accesorios"
    ],
    "repuesto": [
        "repuesto", "repuestos", "refaccion", "refacciones"
    ],
    "controlador": [
        "controlador", "controladores", "indicador", "indicadores"
    ],
    "kit": [
        "kit", "kits"
    ],
    "spool": [
        "spool"
    ],
    "bobina": [
        "bobina", "bobinas"
    ],
    "acoplamiento": [
        "acoplamiento", "acoplamientos"
    ],
}

# ============================================================
# MARCAS INDUSTRIALES PRIORITARIAS
# ============================================================

KNOWN_BRANDS = {
    "siemens",
    "festo",
    "smc",
    "ifm",
    "omron",
    "hyundai",
    "schneider",
    "abb",
    "danfoss",
    "endurance",
    "autonics",
    "metalwork",
    "camozzi",
    "parker",
    "norgren",
    "phoenix",
    "weg",
    "yaskawa",
    "ema",
    "ema-electronic",
    "pixsys",
    "dayton",
    "horiba",
    "yongningan",
    "via",
}

# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def normalizar(texto: str) -> str:
    """
    Convierte cualquier texto a minúsculas, sin acentos y sin
    espacios dobles.
    Ejemplo: 'Válvula   Neumática' → 'valvula neumatica'
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

def _detectar_marcas_conocidas(texto: str) -> set[str]:
    """
    Detecta marcas conocidas dentro de un texto normalizado.
    Se usa búsqueda por substring para soportar variantes como:
    - ema-electronic
    - siemens
    - pixsys
    - dayton
    """
    texto_n = f" {normalizar(texto)} "
    marcas = set()

    for marca in KNOWN_BRANDS:
        marca_n = normalizar(marca)
        if marca_n and marca_n in texto_n:
            marcas.add(marca)

    return marcas


def _texto_principal_doc(doc: dict) -> str:
    """
    Texto principal del producto para evaluar familia industrial.
    Usamos principalmente nombre, categoría y referencias.
    No usamos aplicaciones aquí para evitar clasificaciones engañosas.
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


def _detectar_familias(texto: str) -> set[str]:
    """
    Detecta familias industriales presentes en un texto.
    """
    texto_n = f" {normalizar(texto)} "
    familias = set()

    for familia, aliases in FAMILY_KEYWORDS.items():
        for alias in aliases:
            alias_n = f" {normalizar(alias)} "
            if alias_n in texto_n:
                familias.add(familia)
                break

    return familias


def _detectar_tipos_secundarios(texto: str) -> set[str]:
    """
    Detecta si un texto apunta a accesorios, repuestos, kits,
    controladores o elementos no principales.
    """
    texto_n = f" {normalizar(texto)} "
    tipos = set()

    for tipo, aliases in SECONDARY_KEYWORDS.items():
        for alias in aliases:
            alias_n = f" {normalizar(alias)} "
            if alias_n in texto_n:
                tipos.add(tipo)
                break

    return tipos


def _bonus_por_coincidencias(qn: str, doc: dict, tokens: list[str]) -> float:
    """
    Calcula un bonus adicional por coincidencias más útiles:
    - nombre del producto
    - categorías
    - referencias
    - texto completo
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

    # Coincidencia exacta de frase
    if qn and qn in nombre:
        bonus += 8.0
    if qn and qn in referencias:
        bonus += 10.0
    if qn and qn in categorias:
        bonus += 6.0
    if qn and qn in texto_busqueda:
        bonus += 6.0

    # Coincidencias por token con tope para no desbordar el score
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

def _bonus_por_marca(qn: str, doc: dict) -> float:
    """
    Prioriza productos cuya marca coincide explícitamente
    con la intención del usuario.
    """
    marcas_query = _detectar_marcas_conocidas(qn)
    marcas_doc = _detectar_marcas_conocidas(str(doc.get("MARCA_LET", "")))

    if not marcas_query or not marcas_doc:
        return 0.0

    if marcas_query & marcas_doc:
        return 18.0

    return 0.0


def _ajuste_por_marca(qn: str, doc: dict) -> float:
    """
    Penaliza productos cuya marca no coincide cuando el usuario
    sí especificó una marca conocida.
    """
    marcas_query = _detectar_marcas_conocidas(qn)
    marcas_doc = _detectar_marcas_conocidas(str(doc.get("MARCA_LET", "")))

    if not marcas_query:
        return 0.0

    if not marcas_doc:
        return 0.0

    if marcas_query & marcas_doc:
        return 0.0

    return -25.0


def _bonus_marca_y_familia(qn: str, doc: dict) -> float:
    """
    Prioridad industrial contextual.

    Reglas:
    - Marca + familia coinciden → bonus fuerte
    - Marca coincide pero familia NO → penalización ligera
    - Familia coincide pero marca NO → neutral
    """
    marcas_query = _detectar_marcas_conocidas(qn)
    marcas_doc = _detectar_marcas_conocidas(str(doc.get("MARCA_LET", "")))

    familias_query = _detectar_familias(qn)
    familias_doc = _detectar_familias(_texto_principal_doc(doc))

    if not marcas_query:
        return 0.0

    if marcas_doc and (marcas_query & marcas_doc):
        if familias_query and familias_doc and (familias_query & familias_doc):
            return 24.0
        if familias_query and familias_doc:
            return -18.0
        return 8.0

    return -25.0


def _ajuste_por_familia(qn: str, doc: dict) -> float:
    """
    Ajuste fuerte por coherencia de familia industrial.

    Objetivo:
    - Si el usuario pide MOTOR → priorizar motores reales
    - Si pide SENSOR → priorizar sensores reales
    - Si pide VALVULA → priorizar válvulas reales

    Esto evita que una marca correcta pero de otra categoría
    suba artificialmente en el ranking.
    """
    familias_query = _detectar_familias(qn)
    familias_doc = _detectar_familias(_texto_principal_doc(doc))

    if not familias_query:
        return 0.0

    if familias_query & familias_doc:
        return 26.0

    if familias_doc:
        return -40.0

    return -12.0


def _ajuste_por_tipo_secundario(qn: str, doc: dict) -> float:
    """
    Penaliza accesorios, repuestos, kits o controladores cuando la
    consulta parece apuntar a un equipo principal.

    Ejemplo:
    - "compresor Hyundai" → controlador de temperatura debe bajar
    - "electroválvula 24v" → spool / repuesto debe bajar
    """
    tipos_query = _detectar_tipos_secundarios(qn)
    familias_query = _detectar_familias(qn)

    # Si la consulta ya es explícitamente de accesorio/repuesto,
    # no castigamos nada.
    if tipos_query:
        return 0.0

    texto_doc = _texto_principal_doc(doc)
    tipos_doc = _detectar_tipos_secundarios(texto_doc)

    if not familias_query:
        return 0.0

    if not tipos_doc:
        return 0.0

    # Penalización base por ser secundario
    penalizacion = -8.0

    # Si la consulta es claramente de un equipo principal
    # y el producto es accesorio/repuesto/controlador, la penalización sube.
    if any(f in familias_query for f in ["valvula", "bomba", "compresor", "sensor", "manometro"]):
        penalizacion -= 10.0

    # Si el producto es "controlador" y la consulta pide compresor o válvula,
    # queremos bajarlo más porque suele ser ruido.
    if "controlador" in tipos_doc:
        penalizacion -= 4.0

    # Si es accesorio o repuesto, se penaliza un poco más.
    if "accesorio" in tipos_doc or "repuesto" in tipos_doc or "kit" in tipos_doc:
        penalizacion -= 4.0

    return penalizacion


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
    Búsqueda exacta por código de producto usando el índice CODIGO.
    Más rápida y precisa que RapidFuzz para códigos conocidos.
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

    Esto permite ver:
    - score textual base
    - bonus por coincidencias útiles
    - bonus por marca
    - ajuste por marca
    - ajuste por familia industrial
    - penalización por accesorio/repuesto/controlador
    - bonus comercial
    - score final
    """
    qn = normalizar(q)
    tokens = extraer_tokens(qn)

    texto_busqueda = normalizar(str(doc.get("texto_busqueda", "")))
    nombre = normalizar(str(doc.get("DESCRIPCION_CORTA_PRE", "")))
    referencia = normalizar(str(doc.get("REFERENCIA", "")))
    ref_alt = normalizar(str(doc.get("REF_ALTERNATIVA", "")))

    # Similitudes base
    s1 = fuzz.token_set_ratio(qn, texto_busqueda)
    s2 = fuzz.partial_ratio(qn, texto_busqueda)
    s3 = fuzz.token_sort_ratio(qn, nombre)
    s4 = max(
        fuzz.partial_ratio(qn, referencia),
        fuzz.partial_ratio(qn, ref_alt)
    )

    score_textual = (s1 * 0.35) + (s2 * 0.25) + (s3 * 0.20) + (s4 * 0.15)

    # Bonus extra por coincidencias más útiles
    bonus_coincidencias = _bonus_por_coincidencias(qn, doc, tokens)

    # Bonus/penalización por marca
    bonus_marca = _bonus_por_marca(qn, doc)
    ajuste_marca = _ajuste_por_marca(qn, doc)

    # Bonus combinado marca + familia
    bonus_marca_familia = _bonus_marca_y_familia(qn, doc)

    # Ajuste por familia industrial
    ajuste_familia = _ajuste_por_familia(qn, doc)

    # Penalización por tipo secundario cuando la consulta es de producto base
    ajuste_secundario = _ajuste_por_tipo_secundario(qn, doc)

    # Bonus por score de oportunidad comercial
    bonus_oportunidad = 0.0
    try:
        score_op = float(doc.get("score_oportunidad") or 0)
        if score_op > 0:
            bonus_oportunidad = min(score_op / 100, 1.0) * 5
    except (ValueError, TypeError):
        pass

    score_total = max(
        score_textual
        + bonus_coincidencias
        + bonus_marca
        + bonus_marca_familia
        + ajuste_marca
        + ajuste_familia
        + ajuste_secundario
        + bonus_oportunidad,
        0.0
    )

    return {
        "score_total": round(score_total, 2),
        "score_textual": round(score_textual, 2),
        "bonus_coincidencias": round(bonus_coincidencias, 2),
        "bonus_marca": round(bonus_marca, 2),
        "bonus_marca_familia": round(bonus_marca_familia, 2),
        "ajuste_marca": round(ajuste_marca, 2),
        "ajuste_familia": round(ajuste_familia, 2),
        "ajuste_secundario": round(ajuste_secundario, 2),
        "bonus_oportunidad": round(bonus_oportunidad, 2),
        "s1_token_set": round(s1, 2),
        "s2_partial_texto": round(s2, 2),
        "s3_token_sort_nombre": round(s3, 2),
        "s4_referencia": round(s4, 2),
    }


def score_relevancia(q: str, doc: dict) -> float:
    """
    Mantiene compatibilidad con el código anterior.
    Retorna solo el score total.
    """
    return evaluar_relevancia(q, doc)["score_total"]


# ============================================================
# BÚSQUEDA PRINCIPAL
# ============================================================

def buscar_productos(mensaje: str, limit: int = 8) -> list[dict]:
    """
    Función principal de búsqueda. Recibe texto libre del usuario
    y retorna lista de productos ordenados por relevancia.

    Estrategia en dos fases:
    1. MongoDB filtra candidatos con regex
    2. RapidFuzz + boosts industriales reordenan y depuran
    """
    q_limpia = normalizar(mensaje)
    tokens = extraer_tokens(q_limpia)

    if not tokens:
        return []

    # -------------------------------------------------------
    # Detección de código exacto — búsqueda directa por índice
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
    # FASE 2: Re-ranking con heurística industrial
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
    scored = [(doc, detalle) for doc, detalle in scored if detalle["score_total"] >= UMBRAL_MINIMO]

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
    # Eliminar duplicados manteniendo el de mayor score
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
            "score_total": debug.get("score_total"),
            "score_textual": debug.get("score_textual"),
            "bonus_coincidencias": debug.get("bonus_coincidencias"),
            "bonus_marca": debug.get("bonus_marca"),
            "bonus_marca_familia": debug.get("bonus_marca_familia"),
            "ajuste_marca": debug.get("ajuste_marca"),
            "ajuste_familia": debug.get("ajuste_familia"),
            "ajuste_secundario": debug.get("ajuste_secundario"),
            "bonus_oportunidad": debug.get("bonus_oportunidad"),
        })

    logger.info(
        "[SEARCH_TRACE] %s",
        json.dumps({
            "query": mensaje,
            "total_candidatos": len(candidatos),
            "total_finales": len(resultados),
            "umbral": UMBRAL_MINIMO,
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
    Es el contrato entre el backend y el frontend/NIA.
    Cualquier cambio aquí afecta toda la API.
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
    stock_bog = float(p.get("STOCK_BOG") or 0)
    stock_cali = float(p.get("STOCK_CALI") or 0)
    stock_total = float(p.get("STOCK_TOTAL") or 0)

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
        "codigo":          str(p.get("CODIGO", "")).strip(),
        "referencia":      str(p.get("REFERENCIA", "")).strip(),
        "ref_alternativa": str(p.get("REF_ALTERNATIVA", "")).strip(),

        # Descripción
        "nombre":      str(p.get("DESCRIPCION_CORTA_PRE", "")).strip(),
        "descripcion": str(p.get("DESCRIPCION_LARGA_PRE", "")).strip()[:300],
        "marca":       str(p.get("MARCA_LET", "")).strip(),

        # Jerarquía completa VIA Industrial
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

        # Score comercial — activo cuando llegue Excel de Don Andrés
        "score_oportunidad": score_op,
        "tipo_sku":          str(p.get("tipo_sku", "")).strip(),
    }