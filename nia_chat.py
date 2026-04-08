from fastapi import FastAPI
from pydantic import BaseModel
from pymongo import MongoClient
from rapidfuzz import fuzz
from openai import OpenAI
import re

app = FastAPI(title="NIA Chat Inteligente V2")

# =========================
# CONEXIÓN A MONGO
# =========================
client = MongoClient("mongodb://admin:admin123@localhost:27017/")
db = client["nia"]
collection = db["products_catalog"]

# =========================
# OPENAI
# =========================
client_ai = OpenAI(api_key="TU_API_KEY")  # <-- CAMBIA ESTO

# =========================
# MODELO DE ENTRADA
# =========================
class Pregunta(BaseModel):
    mensaje: str


# =========================
# UTILIDADES
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


def score_producto(q: str, doc: dict) -> float:
    nombre = str(doc.get("nombre", "") or "")
    descripcion = str(doc.get("descripcion", "") or "")
    texto_busqueda = str(doc.get("texto_busqueda", "") or "")
    referencia = str(doc.get("referencia_limpia", "") or "")
    marca = str(doc.get("marca", "") or "")
    categoria = str(doc.get("categoria", "") or "")

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

    # ponderación
    score_final = (s1 * 0.40) + (s2 * 0.25) + (s3 * 0.20) + (s4 * 0.15)
    return round(score_final, 2)


# =========================
# BÚSQUEDA INTELIGENTE EN MONGO
# =========================
def buscar_productos(q: str):
    q_limpia = limpiar_texto(q)
    tokens = extraer_tokens(q_limpia)

    if not tokens:
        return []

    condiciones = []

    # búsqueda por frase completa
    condiciones.extend([
        {"nombre": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"descripcion": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"texto_busqueda": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"referencia_limpia": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"marca": {"$regex": re.escape(q_limpia), "$options": "i"}},
        {"categoria": {"$regex": re.escape(q_limpia), "$options": "i"}},
    ])

    # búsqueda por tokens
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

    # Sin límite fijo pequeño. Mongo trae todos los candidatos que cumplan.
    candidatos = list(collection.find({"$or": condiciones}, proyeccion))

    if not candidatos:
        return []

    resultados = []
    for doc in candidatos:
        score = score_producto(q_limpia, doc)
        doc["score"] = score
        resultados.append(doc)

    # ordenar y tomar los mejores
    resultados = sorted(resultados, key=lambda x: x["score"], reverse=True)

    # quitar duplicados por código o nombre
    unicos = []
    vistos = set()

    for r in resultados:
        clave = (r.get("codigo"), r.get("nombre"))
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(r)

    # top final
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

    resultados = buscar_productos(q)

    if not resultados:
        return {"respuesta": "No encontré productos relacionados."}

    contexto = ""
    for i, r in enumerate(resultados, start=1):
        contexto += (
            f"{i}. "
            f"Nombre: {r.get('nombre', 'N/A')} | "
            f"Marca: {r.get('marca', 'N/A')} | "
            f"Categoría: {r.get('categoria', 'N/A')} | "
            f"Descripción: {r.get('descripcion', 'N/A')} | "
            f"Referencia: {r.get('referencia_limpia', 'N/A')} | "
            f"Score: {r.get('score', 'N/A')}\n"
        )

    prompt = f"""
Eres un asistente comercial técnico experto en productos industriales.

Tu trabajo es responder usando SOLO los productos encontrados.
No inventes referencias, marcas, precios, stock o disponibilidad.
Si hay varias opciones, prioriza las que mejor coincidan con la necesidad del usuario.
Responde en español claro, útil y profesional.

Consulta del usuario:
{q}

Productos encontrados:
{contexto}

Devuelve una recomendación útil indicando cuáles parecen ser las mejores opciones y por qué.
"""

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asesor técnico comercial industrial experto en búsqueda de productos."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return {
            "respuesta": response.choices[0].message.content,
            "resultados": resultados
        }

    except Exception as e:
        return {
            "respuesta": "Ocurrió un error al consultar OpenAI.",
            "detalle": str(e),
            "resultados": resultados
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