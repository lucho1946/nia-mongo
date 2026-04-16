# =========================
# IMPORTACIONES
# =========================
from fastapi import FastAPI
from pydantic import BaseModel
from pymongo import MongoClient
from rapidfuzz import fuzz
from openai import OpenAI
import re
import os
from dotenv import load_dotenv

# =========================
# CARGAR VARIABLES DE ENTORNO
# =========================
load_dotenv()

# =========================
# APP FASTAPI
# =========================
app = FastAPI(title="NIA Chat Inteligente V2")

# =========================
# CONEXIÓN A MONGO (AZURE / ATLAS)
# =========================
MONGO_URI = os.getenv("MONGO_CONNECTION_STRING")

print("🔥 MONGO_URI:", MONGO_URI)

if not MONGO_URI:
    print("Falta MONGO_CONNECTION_STRING en variables de entorno")

client = MongoClient(MONGO_URI)
db = client["nia"]
collection = db["products_catalog"]

# =========================
# OPENAI
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("Falta OPENAI_API_KEY en variables de entorno")

client_ai = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# MODELO DE ENTRADA
# =========================
class Pregunta(BaseModel):
    mensaje: str


# =========================
# UTILIDADES DE TEXTO
# =========================
def limpiar_texto(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def extraer_tokens(texto: str) -> list[str]:
    texto = limpiar_texto(texto)
    tokens = re.findall(r"[a-zA-Z0-9\-\.]+", texto)
    tokens = [t for t in tokens if len(t) >= 2]
    return list(dict.fromkeys(tokens))


# =========================
# SCORING DE PRODUCTOS
# =========================
def score_producto(q: str, doc: dict) -> float:
    nombre = str(doc.get("nombre", ""))
    descripcion = str(doc.get("descripcion", ""))
    texto_busqueda = str(doc.get("texto_busqueda", ""))
    referencia = str(doc.get("referencia_limpia", ""))
    marca = str(doc.get("marca", ""))
    categoria = str(doc.get("categoria", ""))

    bloque = " ".join([
        nombre,
        descripcion,
        texto_busqueda,
        referencia,
        marca,
        categoria
    ])

    s1 = fuzz.token_set_ratio(q, bloque)
    s2 = fuzz.partial_ratio(q, bloque)
    s3 = fuzz.token_sort_ratio(q, nombre)
    s4 = fuzz.partial_ratio(q, referencia)

    score_final = (s1 * 0.40) + (s2 * 0.25) + (s3 * 0.20) + (s4 * 0.15)
    return round(score_final, 2)


# =========================
# BÚSQUEDA EN MONGO
# =========================
def buscar_productos(q: str):
    q_limpia = limpiar_texto(q)
    tokens = extraer_tokens(q_limpia)

    if not tokens:
        return []

    condiciones = []

    condiciones.extend([
        {"nombre": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"descripcion": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"texto_busqueda": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"referencia_limpia": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"marca": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"categoria": {"$regex": re.escape(q_limpia), "$options": "i"}},
    ])

    for token in tokens:
        condiciones.extend([
            {"nombre": {"$regex": re.escape(token), "$options": "i"}},
            {"descripcion": {"$regex": re.escape(token), "$options": "i"}},
            {"texto_busqueda": {"$regex": re.escape(token), "$options": "i"}},
            {"referencia_limpia": {"$regex": re.escape(token), "$options": "i"}},
            {"marca": {"$regex": re.escape(token), "$options": "i"}},
            {"categoria": {"$regex": re.escape(token), "$options": "i"}},
        ])

    proyeccion = {
        "_id": 0,
        "codigo": 1,
        "nombre": 1,
        "marca": 1,
        "categoria": 1,
        "descripcion": 1,
        "texto_busqueda": 1,
        "referencia_limpia": 1,
    }

    candidatos = list(collection.find({"$or": condiciones}, proyeccion))

    if not candidatos:
        return []

    resultados = []
    for doc in candidatos:
        score = score_producto(q_limpia, doc)
        doc["score"] = score
        resultados.append(doc)

    resultados = sorted(resultados, key=lambda x: x["score"], reverse=True)

    unicos = []
    vistos = set()

    for r in resultados:
        clave = (r.get("codigo"), r.get("nombre"))
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(r)

    return unicos[:8]


# =========================
# ENDPOINTS
# =========================
@app.get("/")
def home():
    return {"mensaje": "NIA chat V2 activo"}


@app.post("/chat")
def chat(p: Pregunta):
    q = (p.mensaje or "").strip()

    if not q:
        return {"respuesta": "Debes escribir una consulta."}

    try:
        # 🔥 DEBUG CLAVE
        try:
            resultados = buscar_productos(q)
            print("✅ RESULTADOS OBTENIDOS:", len(resultados))
        except Exception as e:
            print("🔥 ERROR EN BUSCAR_PRODUCTOS:", str(e))
            return {
                "error": "Error en Mongo",
                "detalle": str(e)
            }

        if not resultados:
            return {"respuesta": "No encontré productos relacionados."}

        # 🔥 PRUEBA SIN OPENAI (para aislar problema)
        return {
            "respuesta": "PRUEBA OK SIN OPENAI",
            "resultados": resultados
        }

    except Exception as e:
        print("🔥 ERROR GENERAL:", str(e))
        return {
            "error": str(e)
        }


@app.post("/buscar")
def buscar_directo(p: Pregunta):
    q = (p.mensaje or "").strip()

    if not q:
        return {"items": []}

    resultados = buscar_productos(q)

    return {
        "query": q,
        "total": len(resultados),
        "items": resultados
    }