"""
=============================================================
ETL: SQL Server productos_hugo → MongoDB Atlas
Proyecto: NIA - VIA Industrial
Autor: Luis Díaz
Ejecutar: Sábados 11PM - 5AM
=============================================================

QUÉ HACE ESTE SCRIPT:
1. Se conecta al SQL Server de VIA Industrial (solo lectura)
2. Extrae los campos útiles de la tabla productos_hugo
3. Transforma y limpia los datos
4. Sincroniza con MongoDB Atlas usando upsert por CODIGO
5. Nunca duplica, nunca borra, solo actualiza o inserta

REGLAS:
- Solo lectura en SQL Server — no modifica nada de VIA
- Contraseñas siempre desde variables de entorno (.env)
- Ejecutar en horario acordado: sábados 11PM a 5AM
- En caso de error en una fila, continúa con la siguiente
=============================================================
"""

import os
import logging
from datetime import datetime, timezone

import pyodbc
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

# Carga variables de entorno desde .env
load_dotenv()

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


# =========================
# CONFIGURACIÓN
# =========================

# SQL Server de VIA Industrial
SQL_CONFIG = {
    "server": "144.217.93.12",                  # Servidor VIA Industrial
    "database": "productos",                    # Base de datos
    "username": "productosSoloLectura",         # Usuario solo lectura
    "password": os.getenv("SQL_PASSWORD", ""),  # Contraseña desde .env
    "driver": "ODBC Driver 18 for SQL Server"   # Driver instalado localmente
}

# MongoDB Atlas — cuenta empresarial
MONGO_URI = os.getenv("MONGO_CONNECTION_STRING")  # URI desde .env
MONGO_DB = "nia"                                  # Base de datos NIA
MONGO_COL = "products_catalog"                    # Colección de productos

# Tamaño del batch — cuántos productos se envían a MongoDB de golpe
# 500 es seguro para el plan gratuito de Atlas y sigue siendo eficiente
BATCH_SIZE = 500


# =========================
# QUERY SQL
# =========================
# De las 439 columnas de productos_hugo solo traemos las útiles para NIA
# Filtramos:
#   - BLOQUEADO = 'NO'          → productos bloqueados no deben aparecer
#   - DESCRIPCION_CORTA_PRE     → sin descripción el producto no sirve para NIA

QUERY = """
SELECT
    -- Identificación
    CODIGO,
    REFERENCIA,
    REF_ALTERNATIVA,

    -- Descripción (campos confiables al 100%)
    DESCRIPCION_CORTA_PRE,
    DESCRIPCION_LARGA_PRE,

    -- Comercial
    MARCA_LET,
    PRECIO_VENTA,

    -- Búsqueda
    PALABRAS_CLAVE,

    -- Jerarquía de categorías (4 niveles)
    NIVEL_0,
    NIVEL_1,
    NIVEL_2,
    NIVEL_3,
    NIVEL_4,

    -- Características técnicas (pares título-valor)
    TIT_CAR_IND_1, CAR_IND_1,
    TIT_CAR_IND_2, CAR_IND_2,
    TIT_CAR_IND_3, CAR_IND_3,
    TIT_CAR_IND_4, CAR_IND_4,
    TIT_CAR_IND_5, CAR_IND_5,
    TIT_CAR_IND_6, CAR_IND_6,

    -- Aplicaciones
    APLICACIONES,
    APLICACION_1,
    APLICACION_2,
    APLICACION_3,

    -- Stock por sede
    INVENTARIO_BOG,
    INVENTARIO_CALI,
    STOCK,

    -- Equivalencias
    EQUIVALENTE,
    EQUIVALENTE_2,

    -- Físico
    DIMENSION,
    PESO,

    -- Control
    PV_FECHA,
    VISIBLE_EN_LINEA,
    BLOQUEADO,
    EXISTENCIA

FROM productos_hugo
WHERE DESCRIPCION_CORTA_PRE IS NOT NULL
  AND BLOQUEADO = 'NO'
"""


# =========================
# CONEXIÓN SQL SERVER
# =========================
def conectar_sql():
    """
    Establece conexión con el SQL Server de VIA Industrial.
    Usa el usuario de solo lectura — no puede modificar nada.

    TrustServerCertificate=yes es necesario porque el servidor
    de VIA no tiene certificado SSL configurado.
    """
    if not SQL_CONFIG["password"]:
        raise ValueError("Falta la variable de entorno SQL_PASSWORD")

    conn_str = (
        f"DRIVER={{{SQL_CONFIG['driver']}}};"
        f"SERVER={SQL_CONFIG['server']};"
        f"DATABASE={SQL_CONFIG['database']};"
        f"UID={SQL_CONFIG['username']};"
        f"PWD={SQL_CONFIG['password']};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


# =========================
# CONEXIÓN MONGODB
# =========================
def conectar_mongo():
    """
    Establece conexión con MongoDB Atlas (cuenta empresarial).
    Retorna directamente la colección products_catalog.
    """
    if not MONGO_URI:
        raise ValueError("Falta la variable de entorno MONGO_CONNECTION_STRING")

    client = MongoClient(MONGO_URI)
    return client[MONGO_DB][MONGO_COL]


# =========================
# UTILIDADES DE LIMPIEZA
# =========================
def limpiar(valor):
    """
    Convierte cualquier valor a texto limpio.
    Si viene NULL de SQL Server lo convierte en texto vacío.
    Así MongoDB nunca recibe un None inesperado.
    """
    if valor is None:
        return ""
    return str(valor).strip()


def a_float(valor, default=None):
    """
    Convierte un valor a float de forma segura.
    Si no puede convertirlo, retorna el valor por defecto.
    """
    if valor is None or valor == "":
        return default

    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def a_bool(valor):
    """
    Normaliza valores tipo SQL a booleano real.
    Sirve para columnas BIT, enteros, texto y valores mixtos.
    """
    if isinstance(valor, bool):
        return valor

    if valor is None:
        return False

    if isinstance(valor, (int, float)):
        return valor != 0

    texto = str(valor).strip().lower()
    return texto in {
        "1", "true", "t", "si", "sí", "s", "y", "yes",
        "activo", "activa", "on"
    }


# =========================
# CONSTRUCCIÓN DE CARACTERÍSTICAS TÉCNICAS
# =========================
def construir_caracteristicas(row):
    """
    Las características técnicas en SQL Server vienen como pares de columnas:
        TIT_CAR_IND_1 = título  (ej: "Rango de Temperatura")
        CAR_IND_1     = valor   (ej: "-20ºC a 250ºC")

    Esta función los convierte en una lista de objetos legibles:
        [{"titulo": "Rango de Temperatura", "valor": "-20ºC a 250ºC"}, ...]

    Solo incluye el par si al menos uno de los dos tiene dato.
    """
    pares = [
        (limpiar(row.TIT_CAR_IND_1), limpiar(row.CAR_IND_1)),
        (limpiar(row.TIT_CAR_IND_2), limpiar(row.CAR_IND_2)),
        (limpiar(row.TIT_CAR_IND_3), limpiar(row.CAR_IND_3)),
        (limpiar(row.TIT_CAR_IND_4), limpiar(row.CAR_IND_4)),
        (limpiar(row.TIT_CAR_IND_5), limpiar(row.CAR_IND_5)),
        (limpiar(row.TIT_CAR_IND_6), limpiar(row.CAR_IND_6)),
    ]
    return [{"titulo": t, "valor": v} for t, v in pares if t or v]


# =========================
# CONSTRUCCIÓN DE TEXTO DE BÚSQUEDA
# =========================
def construir_texto_busqueda(row, caracteristicas):
    """
    Campo clave para NIA. Concatena todos los campos útiles en un
    solo texto en minúsculas para que RapidFuzz pueda buscar.

    Cuando el cliente escribe "cámara termográfica flir", NIA busca
    en este campo y encuentra el producto correcto.

    Sin este campo la búsqueda es ciega.
    """
    partes = [
        limpiar(row.DESCRIPCION_CORTA_PRE),
        limpiar(row.DESCRIPCION_LARGA_PRE),
        limpiar(row.MARCA_LET),
        limpiar(row.REFERENCIA),
        limpiar(row.REF_ALTERNATIVA),
        limpiar(row.PALABRAS_CLAVE),
        limpiar(row.NIVEL_0),
        limpiar(row.NIVEL_1),
        limpiar(row.NIVEL_2),
        limpiar(row.NIVEL_3),
        limpiar(row.NIVEL_4),
        limpiar(row.APLICACIONES),
        limpiar(row.APLICACION_1),
        limpiar(row.APLICACION_2),
        limpiar(row.APLICACION_3),
        limpiar(row.EQUIVALENTE),
        limpiar(row.EQUIVALENTE_2),
    ]

    # También incluye las características técnicas en el texto de búsqueda
    for c in caracteristicas:
        partes.append(c["titulo"])
        partes.append(c["valor"])

    return " ".join(filter(None, partes)).lower()


# =========================
# TRANSFORMACIÓN
# =========================
def transformar(row) -> dict:
    """
    Toma una fila cruda del SQL Server y la convierte en un documento
    limpio y estructurado listo para MongoDB.

    Aplica:
    - limpiar()                    → elimina NULLs y espacios
    - construir_caracteristicas()  → pares título-valor
    - construir_texto_busqueda()   → campo unificado para búsqueda NIA
    """
    caracteristicas = construir_caracteristicas(row)
    texto_busqueda = construir_texto_busqueda(row, caracteristicas)

    return {
        # Identificación
        "CODIGO": limpiar(row.CODIGO),
        "REFERENCIA": limpiar(row.REFERENCIA),
        "REF_ALTERNATIVA": limpiar(row.REF_ALTERNATIVA),

        # Descripción
        "DESCRIPCION_CORTA_PRE": limpiar(row.DESCRIPCION_CORTA_PRE),
        "DESCRIPCION_LARGA_PRE": limpiar(row.DESCRIPCION_LARGA_PRE),

        # Comercial
        "MARCA_LET": limpiar(row.MARCA_LET),
        "PRECIO_VENTA": a_float(row.PRECIO_VENTA, default=None),

        # Jerarquía de categorías
        "NIVEL_0": limpiar(row.NIVEL_0),
        "NIVEL_1": limpiar(row.NIVEL_1),
        "NIVEL_2": limpiar(row.NIVEL_2),
        "NIVEL_3": limpiar(row.NIVEL_3),
        "NIVEL_4": limpiar(row.NIVEL_4),

        # Características técnicas estructuradas
        "CARACTERISTICAS": caracteristicas,

        # Aplicaciones
        "APLICACIONES": limpiar(row.APLICACIONES),

        # Stock por sede
        "STOCK_BOG": a_float(row.INVENTARIO_BOG, default=0.0) or 0.0,
        "STOCK_CALI": a_float(row.INVENTARIO_CALI, default=0.0) or 0.0,
        "STOCK_TOTAL": a_float(row.STOCK, default=0.0) or 0.0,

        # Equivalencias
        "EQUIVALENTE": limpiar(row.EQUIVALENTE),
        "EQUIVALENTE_2": limpiar(row.EQUIVALENTE_2),

        # Físico
        "DIMENSION": limpiar(row.DIMENSION),
        "PESO": a_float(row.PESO, default=None),

        # Control
        "PV_FECHA": row.PV_FECHA.isoformat() if row.PV_FECHA else None,
        "VISIBLE_EN_LINEA": a_bool(row.VISIBLE_EN_LINEA),

        # Tiempo estimado de entrega — campo EXISTENCIA de SQL Server
        "EXISTENCIA": limpiar(row.EXISTENCIA),

        # Campo clave para búsqueda NIA con RapidFuzz
        "texto_busqueda": texto_busqueda,

        # Fecha de sincronización — cuándo fue la última vez que el ETL actualizó este producto
        "etl_fecha": datetime.now(timezone.utc).isoformat(),
    }


# =========================
# ETL PRINCIPAL
# =========================
def ejecutar_etl():
    """
    Proceso principal del ETL.

    Flujo:
    1. Conecta a SQL Server y MongoDB
    2. Ejecuta el query y recorre fila por fila
    3. Transforma cada fila al formato MongoDB
    4. Acumula operaciones en batches de 500
    5. Envía cada batch a MongoDB con bulk_write
    6. Si una fila falla, registra el error y continúa
    7. Al final reporta total procesados y errores
    """
    log.info("=" * 60)
    log.info("Iniciando ETL SQL Server → MongoDB")
    log.info(f"Base SQL: {SQL_CONFIG['database']} | Tabla: productos_hugo")
    log.info(f"Base Mongo: {MONGO_DB} | Colección: {MONGO_COL}")
    log.info("=" * 60)

    # Conexiones
    conn_sql = conectar_sql()
    col_mongo = conectar_mongo()
    log.info("Conexiones establecidas correctamente")

    cursor = None
    try:
        # Ejecutar query
        cursor = conn_sql.cursor()
        cursor.execute(QUERY)
        columnas = [col[0] for col in cursor.description]
        log.info("Query ejecutado — comenzando sincronización")

        # Contadores
        total = 0
        errores = 0
        operaciones = []

        for fila in cursor:
            try:
                # Convierte la fila en objeto con atributos accesibles por nombre
                row = type("Row", (), dict(zip(columnas, fila)))()

                # Transforma la fila al formato MongoDB
                doc = transformar(row)

                # Upsert por CODIGO:
                # - Si existe → actualiza todos los campos
                # - Si no existe → inserta nuevo
                # Nunca duplica, nunca borra
                operaciones.append(
                    UpdateOne(
                        {"CODIGO": doc["CODIGO"]},
                        {"$set": doc},
                        upsert=True
                    )
                )

                # Cuando acumula 500 operaciones las envía a MongoDB
                if len(operaciones) >= BATCH_SIZE:
                    col_mongo.bulk_write(operaciones, ordered=False)
                    total += len(operaciones)
                    log.info(f"Sincronizados: {total:,} productos")
                    operaciones = []

            except Exception as e:
                # Si una fila falla, registra el error y continúa con la siguiente
                # No detiene todo el proceso por un producto con datos corruptos
                errores += 1
                log.error(f"Error en fila {total + errores}: {e}")
                continue

        # Envía el último batch que quedó pendiente
        if operaciones:
            col_mongo.bulk_write(operaciones, ordered=False)
            total += len(operaciones)

        log.info("=" * 60)
        log.info("ETL completado exitosamente")
        log.info(f"Total sincronizados : {total:,}")
        log.info(f"Total errores       : {errores:,}")
        log.info("=" * 60)

        return {"procesados": total, "errores": errores}

    finally:
        # Cierra conexiones aunque ocurra un error
        if cursor is not None:
            cursor.close()
        conn_sql.close()


# =========================
# QUERY INVENTARIO
# =========================
QUERY_INVENTARIO = """
SELECT
    INVENTARIO_CODIGO,
    INVENTARIO,
    INVENTARIO_FECHA
FROM inventario
WHERE INVENTARIO > 0
"""


# =========================
# ETL INVENTARIO
# =========================
def ejecutar_etl_inventario():
    """
    Proceso secundario del ETL.

    Lee la tabla inventario de SQL Server y actualiza
    el stock en tiempo real de cada producto en MongoDB.

    Flujo:
    1. Toma los productos con inventario positivo
    2. Actualiza STOCK_TOTAL e INVENTARIO_FECHA
    3. Marca la corrida con etl_inventario_fecha
    4. Al final deja en cero los productos que no aparecieron en esta corrida

    Esto evita que MongoDB conserve stock viejo cuando un producto
    ya no tiene inventario en la fuente.
    """
    log.info("=" * 60)
    log.info("Iniciando ETL Inventario → MongoDB")
    log.info("=" * 60)

    run_id = datetime.now(timezone.utc).isoformat()

    conn_sql = conectar_sql()
    col_mongo = conectar_mongo()

    cursor = None
    try:
        cursor = conn_sql.cursor()
        cursor.execute(QUERY_INVENTARIO)

        total = 0
        errores = 0
        codigos_actualizados = set()

        for fila in cursor:
            try:
                codigo = limpiar(fila[0])
                cantidad = a_float(fila[1], default=0.0) or 0.0
                fecha_inventario = fila[2].isoformat() if fila[2] else None

                if not codigo:
                    continue

                # Actualizar stock en tiempo real en MongoDB
                # Solo actualiza — no inserta productos nuevos
                resultado = col_mongo.update_one(
                    {"CODIGO": codigo},
                    {
                        "$set": {
                            "STOCK_TOTAL": float(cantidad),
                            "INVENTARIO_FECHA": fecha_inventario,
                            "etl_inventario_fecha": run_id
                        }
                    }
                )

                if resultado.matched_count > 0:
                    total += 1
                    codigos_actualizados.add(codigo)

            except Exception as e:
                errores += 1
                log.error(f"Error actualizando inventario: {e}")
                continue

        # Limpieza final:
        # Si un producto no fue actualizado en esta corrida,
        # se considera sin inventario y se deja en 0.
        #
        # Esto evita que un stock viejo se quede “pegado” en MongoDB.
        if codigos_actualizados:
            resultado_limpieza = col_mongo.update_many(
                {"CODIGO": {"$nin": list(codigos_actualizados)}},
                {
                    "$set": {
                        "STOCK_TOTAL": 0.0,
                        "INVENTARIO_FECHA": None,
                        "etl_inventario_fecha": run_id
                    }
                }
            )
            log.info(
                "Limpieza de stock viejo aplicada a "
                f"{resultado_limpieza.modified_count:,} productos"
            )
        else:
            log.warning(
                "No se encontraron productos con inventario positivo. "
                "No se aplicó limpieza de stock viejo."
            )

        log.info(f"ETL Inventario completado. Actualizados: {total:,} | Errores: {errores:,}")
        log.info("=" * 60)
        return {"actualizados": total, "errores": errores}

    finally:
        if cursor is not None:
            cursor.close()
        conn_sql.close()


# =========================
# PUNTO DE ENTRADA
# =========================
if __name__ == "__main__":
    # Paso 1 — Cargar productos completos
    resultado_productos = ejecutar_etl()
    print(f"Productos: {resultado_productos}")

    # Paso 2 — Actualizar stock en tiempo real
    resultado_inventario = ejecutar_etl_inventario()
    print(f"Inventario: {resultado_inventario}")
    