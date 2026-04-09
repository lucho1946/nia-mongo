from pathlib import Path
from fastapi import FastAPI, Query
import json
import re
import unicodedata
from difflib import SequenceMatcher
import os
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

load_dotenv()

app = FastAPI(title="NIA API", version="5.0.0")

ARCHIVO_DATOS = "productos.json"

POSIBLES_CLAVES_CODIGO = [
    "codigo", "Código", "CODIGO", "código",
    "referencia", "REFERENCIA", "Referencia",
    "sku", "SKU", "id", "ID"
]

productos = []
col_codigo = None
claves_disponibles = []


# =========================
# DESCARGA DESDE AZURE STORAGE
# =========================
def descargar_productos_json():
    ruta = Path(ARCHIVO_DATOS)
    if ruta.exists():
        print("productos.json ya existe, no se descarga.")
        return
    print("Descargando productos.json desde Azure Storage...")
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("No se encontró AZURE_STORAGE_CONNECTION_STRING en las variables de entorno.")
    client = BlobServiceClient.from_connection_string(conn_str)
    blob = client.get_blob_client(container="datos", blob="productos.json")
    with open(ruta, "wb") as f:
        f.write(blob.download_blob().readall())
    print("productos.json descargado exitosamente.")


# =========================
# UTILIDADES
# =========================
def quitar_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(texto))
        if not unicodedata.combining(c)
    )


def normalizar_texto(texto: str) -> str:
    texto = str(texto).strip().lower()
    texto = quitar_acentos(texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto


def similitud(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def parece_codigo(q: str) -> bool:
    q = q.strip()
    return bool(re.fullmatch(r"[A-Za-z0-9\-_]+", q)) and len(q) >= 3 and " " not in q


def detectar_clave_codigo(lista_productos: list) -> str:
    if not lista_productos:
        raise ValueError("El archivo JSON no contiene productos.")

    ejemplo = lista_productos[0]
    claves_normalizadas = {normalizar_texto(k): k for k in ejemplo.keys()}

    for posible in POSIBLES_CLAVES_CODIGO:
        clave_n = normalizar_texto(posible)
        if clave_n in claves_normalizadas:
            return claves_normalizadas[clave_n]

    raise ValueError(
        f"No se encontró una clave de código. Claves disponibles: {list(ejemplo.keys())}"
    )


def valor(p: dict, campo: str) -> str:
    return str(p.get(campo, "")).strip()


def limpiar_producto(p: dict) -> dict:
    return {
        "codigo": valor(p, col_codigo),
        "nombre": valor(p, "nombre"),
        "marca": valor(p, "marca"),
        "categoria": valor(p, "categoria"),
        "descripcion": valor(p, "descripcion"),
        "referencia": valor(p, "referencia_limpia"),
        "texto_busqueda": valor(p, "texto_buscado_expandido"),
        "bloqueado": valor(p, "bloqueado"),
    }


def cargar_datos():
    global productos, col_codigo, claves_disponibles

    ruta = Path(ARCHIVO_DATOS)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {ARCHIVO_DATOS}")

    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "productos" in data and isinstance(data["productos"], list):
            productos = data["productos"]
        else:
            raise ValueError("El JSON no contiene una lista en la clave 'productos'.")
    elif isinstance(data, list):
        productos = data
    else:
        raise ValueError("Formato JSON inválido.")

    if not productos:
        raise ValueError("El archivo JSON está vacío.")

    productos_limpios = []
    for p in productos:
        item = {}
        for k, v in p.items():
            item[str(k).strip()] = "" if v is None else str(v).strip()
        productos_limpios.append(item)

    productos = productos_limpios
    col_codigo = detectar_clave_codigo(productos)
    claves_disponibles = list(productos[0].keys())


def score_producto(p: dict, q: str) -> float:
    qn = normalizar_texto(q)
    tokens = [t for t in qn.split() if t]

    codigo = normalizar_texto(valor(p, col_codigo))
    nombre = normalizar_texto(valor(p, "nombre"))
    nombre_final = normalizar_texto(valor(p, "nombre_final"))
    marca = normalizar_texto(valor(p, "marca"))
    categoria = normalizar_texto(valor(p, "categoria"))
    descripcion = normalizar_texto(valor(p, "descripcion"))
    referencia = normalizar_texto(valor(p, "referencia_limpia"))
    texto_expandido = normalizar_texto(valor(p, "texto_buscado_expandido"))
    palabras = normalizar_texto(valor(p, "palabras_clave_limpias"))

    s = 0.0

    if codigo == qn:
        s += 1000
    if nombre == qn:
        s += 500
    if nombre_final == qn:
        s += 480
    if referencia == qn:
        s += 450

    if qn and qn in codigo:
        s += 300
    if qn and qn in nombre:
        s += 220
    if qn and qn in nombre_final:
        s += 210
    if qn and qn in referencia:
        s += 180
    if qn and qn in marca:
        s += 80
    if qn and qn in categoria:
        s += 70
    if qn and qn in descripcion:
        s += 50
    if qn and qn in texto_expandido:
        s += 45
    if qn and qn in palabras:
        s += 45

    for t in tokens:
        if t in codigo:
            s += 60
        if t in nombre:
            s += 50
        if t in nombre_final:
            s += 48
        if t in referencia:
            s += 45
        if t in marca:
            s += 20
        if t in categoria:
            s += 18
        if t in descripcion:
            s += 10
        if t in texto_expandido:
            s += 8
        if t in palabras:
            s += 8

    s += similitud(qn, codigo) * 120
    s += similitud(qn, nombre) * 80
    s += similitud(qn, nombre_final) * 75
    s += similitud(qn, referencia) * 70

    return round(s, 2)


# Arranque: descarga el JSON si no existe y carga los datos
descargar_productos_json()
cargar_datos()


# =========================
# ENDPOINTS
# =========================
@app.get("/")
def root():
    return {
        "ok": True,
        "version": "5.0.0",
        "archivo": ARCHIVO_DATOS,
        "columna_codigo": col_codigo,
        "total_productos": len(productos)
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "archivo": ARCHIVO_DATOS,
        "total_productos": len(productos)
    }


@app.get("/resumen")
def resumen():
    return {
        "archivo": ARCHIVO_DATOS,
        "total_registros": len(productos),
        "claves": claves_disponibles,
        "columna_codigo": col_codigo
    }


@app.get("/producto/{codigo}")
def get_producto(codigo: str):
    codigo_n = normalizar_texto(codigo)

    resultado = [
        limpiar_producto(p) for p in productos
        if normalizar_texto(valor(p, col_codigo)) == codigo_n
    ]

    return {
        "query": codigo,
        "total_encontrados": len(resultado),
        "resultados": resultado
    }


@app.get("/buscar")
def buscar(
    q: str = Query(..., min_length=1, description="Texto libre o código"),
    limit: int = Query(default=10, ge=1, le=50)
):
    q = str(q).strip()
    qn = normalizar_texto(q)

    if parece_codigo(q):
        exactos = [
            limpiar_producto(p) for p in productos
            if normalizar_texto(valor(p, col_codigo)) == qn
        ]
        if exactos:
            return {
                "query": q,
                "tipo_busqueda": "codigo_exacto",
                "total_encontrados": len(exactos),
                "resultados": exactos[:limit]
            }

    resultados = []
    for p in productos:
        s = score_producto(p, q)
        if s > 0:
            item = limpiar_producto(p)
            item["_score"] = s
            resultados.append(item)

    resultados.sort(key=lambda x: x["_score"], reverse=True)

    return {
        "query": q,
        "tipo_busqueda": "relevancia",
        "total_encontrados": len(resultados),
        "resultados": resultados[:limit]
    }


@app.post("/recargar")
def recargar():
    cargar_datos()
    return {
        "ok": True,
        "mensaje": "Datos recargados",
        "total_productos": len(productos),
        "columna_codigo": col_codigo
    }