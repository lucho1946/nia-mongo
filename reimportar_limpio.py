# ============================================================
# reimportar_limpio.py
# Vacía la colección actual en MongoDB y carga los datos limpios.
# Ejecutar UNA sola vez después de limpiar_productos.py.
# ============================================================

from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv
import json
import os

load_dotenv()

ARCHIVO = "productos_limpio.json"
BATCH_SIZE = 1000

def main():
    uri = os.getenv("MONGO_CONNECTION_STRING")
    if not uri:
        raise RuntimeError("MONGO_CONNECTION_STRING no encontrado en .env")

    print("Conectando a MongoDB Atlas...")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    db = client["nia"]
    collection = db["products_catalog"]

    # --- Verificar conexión ---
    client.admin.command("ping")
    print("Conexión exitosa.")

    # --- Cargar JSON ---
    print(f"Cargando {ARCHIVO}...")
    with open(ARCHIVO, "r", encoding="utf-8") as f:
        productos = json.load(f)
    print(f"Total a importar: {len(productos):,}")

    # --- Vaciar colección actual ---
    print("Vaciando colección actual...")
    resultado = collection.delete_many({})
    print(f"Documentos eliminados: {resultado.deleted_count:,}")

    # --- Insertar en bloques ---
    print("Insertando datos limpios...")
    insertados = 0
    for i in range(0, len(productos), BATCH_SIZE):
        batch = productos[i:i + BATCH_SIZE]
        collection.insert_many(batch)
        insertados += len(batch)
        print(f"  Insertados: {insertados:,} / {len(productos):,}")

    # --- Crear índices para búsqueda rápida ---
    print("Creando índices...")
    collection.create_index([("codigo", ASCENDING)], unique=True)
    collection.create_index([("nombre", ASCENDING)])
    collection.create_index([("marca", ASCENDING)])
    collection.create_index([("categoria", ASCENDING)])
    print("Índices creados.")

    # --- Verificación final ---
    total_final = collection.count_documents({})
    print(f"\nTotal documentos en MongoDB: {total_final:,}")
    print("Reimportación completada.")

if __name__ == "__main__":
    main()