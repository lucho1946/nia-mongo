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
import pyodbc
from pymongo import MongoClient, UpdateOne
from datetime import datetime, timezone
from dotenv import load_dotenv
import logging

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
    "server":   "144.217.93.12",          # Servidor VIA Industrial
    "database": "productos",               # Base de datos
    "username": "productosSoloLectura",    # Usuario solo lectura
    "password": os.getenv("SQL_PASSWORD", ""),  # Contraseña desde .env
    "driver":   "ODBC Driver 18 for SQL Server" # Driver instalado localmente
}

# MongoDB Atlas — cuenta empresarial
MONGO_URI = os.getenv("MONGO_CONNECTION_STRING")  # URI desde .env
MONGO_DB  = "nia"                                  # Base de datos NIA
MONGO_COL = "products_catalog"                     # Colección de productos

# Tamaño del batch — cuántos productos se envían a MongoDB de un golpe
# 500 es seguro para el plan gratuito de Atlas
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
    BLOQUEADO

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
    texto_busqueda  = construir_texto_busqueda(row, caracteristicas)

    return {
        # Identificación
        "CODIGO":                limpiar(row.CODIGO),
        "REFERENCIA":            limpiar(row.REFERENCIA),
        "REF_ALTERNATIVA":       limpiar(row.REF_ALTERNATIVA),

        # Descripción
        "DESCRIPCION_CORTA_PRE": limpiar(row.DESCRIPCION_CORTA_PRE),
        "DESCRIPCION_LARGA_PRE": limpiar(row.DESCRIPCION_LARGA_PRE),

        # Comercial
        "MARCA_LET":             limpiar(row.MARCA_LET),
        "PRECIO_VENTA":          float(row.PRECIO_VENTA) if row.PRECIO_VENTA else None,

        # Jerarquía de categorías
        "NIVEL_0":               limpiar(row.NIVEL_0),
        "NIVEL_1":               limpiar(row.NIVEL_1),
        "NIVEL_2":               limpiar(row.NIVEL_2),
        "NIVEL_3":               limpiar(row.NIVEL_3),
        "NIVEL_4":               limpiar(row.NIVEL_4),

        # Características técnicas estructuradas
        "CARACTERISTICAS":       caracteristicas,

        # Aplicaciones
        "APLICACIONES":          limpiar(row.APLICACIONES),

        # Stock por sede
        "STOCK_BOG":             float(row.INVENTARIO_BOG) if row.INVENTARIO_BOG else 0,
        "STOCK_CALI":            float(row.INVENTARIO_CALI) if row.INVENTARIO_CALI else 0,
        "STOCK_TOTAL":           float(row.STOCK) if row.STOCK else 0,

        # Equivalencias
        "EQUIVALENTE":           limpiar(row.EQUIVALENTE),
        "EQUIVALENTE_2":         limpiar(row.EQUIVALENTE_2),

        # Físico
        "DIMENSION":             limpiar(row.DIMENSION),
        "PESO":                  float(row.PESO) if row.PESO else None,

        # Control
        "PV_FECHA":              row.PV_FECHA.isoformat() if row.PV_FECHA else None,
        "VISIBLE_EN_LINEA":      bool(row.VISIBLE_EN_LINEA),

        # Campo clave para búsqueda NIA con RapidFuzz
        "texto_busqueda":        texto_busqueda,

        # Fecha de sincronización — cuándo fue la última vez que el ETL actualizó este producto
        "etl_fecha":             datetime.now(timezone.utc).isoformat(),
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
    conn_sql  = conectar_sql()
    col_mongo = conectar_mongo()
    log.info("Conexiones establecidas correctamente")

    # Ejecutar query
    cursor = conn_sql.cursor()
    cursor.execute(QUERY)
    columnas = [col[0] for col in cursor.description]
    log.info("Query ejecutado — comenzando sincronización")

    # Contadores
    total       = 0
    errores     = 0
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

    # Cierra conexiones
    cursor.close()
    conn_sql.close()

    log.info("=" * 60)
    log.info(f"ETL completado exitosamente")
    log.info(f"Total sincronizados : {total:,}")
    log.info(f"Total errores       : {errores:,}")
    log.info("=" * 60)

    return {"procesados": total, "errores": errores}


# =========================
# PUNTO DE ENTRADA
# =========================
if __name__ == "__main__":
    resultado = ejecutar_etl()
    print(resultado)