# ============================================================
# services/mongo.py
# Responsabilidad única: gestionar la conexión a MongoDB Atlas
# Todo el proyecto importa desde aquí. Nunca se conecta directo.
# ============================================================

from pymongo import MongoClient
import os
import logging

# Logger propio de este módulo.
# Aparece en logs como "services.mongo" — fácil de filtrar en Azure.
logger = logging.getLogger(__name__)

# Variable global que guarda la conexión activa.
# Empieza en None — no se conecta al importar el módulo,
# sino solo cuando alguien realmente necesita la base de datos.
# Esto se llama patrón "lazy initialization".
_client: MongoClient | None = None


def get_client() -> MongoClient:
    """
    Retorna el cliente MongoDB.
    Si ya existe una conexión activa, la reutiliza (no abre una nueva).
    Si no existe, la crea usando la variable de entorno.
    
    Esto es crítico en producción con Gunicorn multi-worker:
    cada worker crea su propia conexión una sola vez y la mantiene.
    """
    global _client

    if _client is None:
        # Lee la URI desde variables de entorno (.env local / Azure App Settings)
        # Nunca hardcodear credenciales en el código.
        uri = os.getenv("MONGO_CONNECTION_STRING")

        if not uri:
            # Falla rápido con mensaje claro.
            # Es mejor crashear al inicio que fallar silenciosamente después.
            raise RuntimeError("MONGO_CONNECTION_STRING no configurado")

        # serverSelectionTimeoutMS=5000 → si Mongo no responde en 5 segundos,
        # lanza excepción inmediata en lugar de colgar el servidor indefinidamente.
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        logger.info("Conexión MongoDB establecida")

    return _client


def get_db():
    """
    Retorna la base de datos 'nia' dentro del cluster.
    Si mañana cambias el nombre de la DB, lo cambias aquí y punto.
    """
    return get_client()["nia"]


def get_collection():
    """
    Retorna la colección 'products_catalog'.
    Es lo que usan los routers para hacer find(), count_documents(), etc.
    Centralizar esto evita que cada archivo escriba el nombre distinto
    y luego nadie sepa cuál es el correcto.
    """
    return get_db()["products_catalog"]