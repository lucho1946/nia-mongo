from pathlib import Path
from fastapi import FastAPI, Query
from contextlib import asynccontextmanager
import json
import re
import unicodedata
from difflib import SequenceMatcher
import os
import threading
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

load_dotenv()

ARCHIVO_DATOS = "productos.json"

POSIBLES_CLAVES_CODIGO = [
    "codigo", "Código", "CODIGO", "código",
    "referencia", "REFERENCIA", "Referencia",
    "sku", "SKU", "id", "ID"
]

productos = []
col_codigo = None
claves_disponibles = []
datos_listos = False


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
    raise ValueError(f"No se encontró clave de código. Claves: {list(ejemplo.keys())}")

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
        "precio": valor(p, "precio"),
    }


# =========================
# 🔥 CARGA DE DATOS (NO SE TOCA)
# =========================
def cargar_datos_background():
    global productos, col_codigo, claves_disponibles, datos_listos

    try:
        print("Intentando cargar datos...")

        ruta = Path(ARCHIVO_DATOS)

        if ruta.exists():
            print("Cargando desde archivo local...")
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)

        else:
            print("Intentando cargar desde Azure...")

            conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

            if not conn_str:
                print("No hay conexión a Azure Storage")
                data = []

            else:
                try:
                    client = BlobServiceClient.from_connection_string(conn_str)
                    blob = client.get_blob_client(container="datos", blob="productos.json")
                    contenido = blob.download_blob().readall()
                    data = json.loads(contenido.decode("utf-8"))
                    print("Datos cargados desde Azure")
                except Exception as e:
                    print(f"Error Azure: {e}")
                    data = []

        productos_raw = data if isinstance(data, list) else data.get("productos", [])

        productos_limpios = []
        for p in productos_raw:
            item = {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in p.items()}
            productos_limpios.append(item)

        productos = productos_limpios

        if productos:
            col_codigo = detectar_clave_codigo(productos)
            claves_disponibles = list(productos[0].keys())

        datos_listos = True
        print(f"Productos cargados: {len(productos)}")

    except Exception as e:
        print(f"ERROR GENERAL: {e}")
        datos_listos = False


# =========================
# 🚨 CAMBIO CLAVE (SOLUCIÓN)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 🔥 IMPORTANTE:
    # Antes se ejecutaba la carga de datos aquí
    # Eso hacía que si fallaba Azure o el JSON → la app se caía
    # Ahora NO se ejecuta automáticamente
    print("App iniciando sin carga automática de datos...")
    yield


app = FastAPI(title="NIA API", version="5.0.0", lifespan=lifespan)


# =========================
# SCORE
# =========================
def score_producto(p: dict, q: str) -> float:
    qn = normalizar_texto(q)
    tokens = [t for t in qn.split() if t]

    codigo = normalizar_texto(valor(p, col_codigo))
    nombre = normalizar_texto(valor(p, "nombre"))
    marca = normalizar_texto(valor(p, "marca"))
    categoria = normalizar_texto(valor(p, "categoria"))
    descripcion = normalizar_texto(valor(p, "descripcion"))
    referencia = normalizar_texto(valor(p, "referencia_limpia"))
    texto_expandido = normalizar_texto(valor(p, "texto_buscado_expandido"))

    s = 0.0
    if codigo == qn: s += 1000
    if nombre == qn: s += 500
    if referencia == qn: s += 450
    if qn in codigo: s += 300
    if qn in nombre: s += 220
    if qn in referencia: s += 180
    if qn in marca: s += 80
    if qn in categoria: s += 70
    if qn in descripcion: s += 50
    if qn in texto_expandido: s += 45

    for t in tokens:
        if t in codigo: s += 60
        if t in nombre: s += 50
        if t in referencia: s += 45
        if t in marca: s += 20
        if t in categoria: s += 18
        if t in descripcion: s += 10
        if t in texto_expandido: s += 8

    s += similitud(qn, codigo) * 120
    s += similitud(qn, nombre) * 80
    s += similitud(qn, referencia) * 70
    return round(s, 2)


# =========================
# ENDPOINTS
# =========================
@app.get("/")
def root():
    return {
        "ok": True,
        "version": "5.0.0",
        "datos_listos": datos_listos,
        "total_productos": len(productos)
    }

@app.get("/health")
def health():
    return {
        "status": "ok" if datos_listos else "cargando",
        "total_productos": len(productos)
    }

@app.get("/resumen")
def resumen():
    return {
        "total_registros": len(productos),
        "claves": claves_disponibles,
        "columna_codigo": col_codigo,
        "datos_listos": datos_listos
    }

@app.get("/producto/{codigo}")
def get_producto(codigo: str):
    if not datos_listos:
        return {"mensaje": "Cargando datos...", "datos_listos": False}
    codigo_n = normalizar_texto(codigo)
    resultado = [limpiar_producto(p) for p in productos if normalizar_texto(valor(p, col_codigo)) == codigo_n]
    return {"query": codigo, "total_encontrados": len(resultado), "resultados": resultado}

@app.get("/buscar")
def buscar(q: str = Query(..., min_length=1), limit: int = Query(default=10, ge=1, le=50)):
    if not datos_listos:
        return {"mensaje": "Cargando datos...", "datos_listos": False}

    qn = normalizar_texto(q)

    if parece_codigo(q):
        exactos = [limpiar_producto(p) for p in productos if normalizar_texto(valor(p, col_codigo)) == qn]
        if exactos:
            return {"query": q, "tipo_busqueda": "codigo_exacto", "resultados": exactos[:limit]}

    resultados = []
    for p in productos:
        s = score_producto(p, q)
        if s > 0:
            item = limpiar_producto(p)
            item["_score"] = s
            resultados.append(item)

    resultados.sort(key=lambda x: x["_score"], reverse=True)
    return {"query": q, "tipo_busqueda": "relevancia", "resultados": resultados[:limit]}


@app.post("/recargar")
def recargar():
    hilo = threading.Thread(target=cargar_datos_background, daemon=True)
    hilo.start()
    return {"ok": True, "mensaje": "Recarga iniciada"}