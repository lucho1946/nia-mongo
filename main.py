# ============================================================
# main.py
# Entrypoint único de la aplicación NIA.
#
# Este es el archivo que arranca todo.
# Gunicorn/Uvicorn apunta aquí en local y en Azure.
#
# Responsabilidades:
# 1) Cargar variables de entorno.
# 2) Configurar logging.
# 3) Crear la instancia FastAPI.
# 4) Configurar CORS.
# 5) Registrar todos los routers del backend.
#
# Este archivo NO debe contener lógica de negocio.
# La lógica vive en routers/, services/, orchestration/, memory/, etc.
# ============================================================

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware 


# ============================================================
# CARGA DE VARIABLES DE ENTORNO
# ============================================================
# En local:
# - toma valores desde .env.
#
# En Azure App Service:P
# - toma valores desde Application Settings.
#
# Importante:
# load_dotenv() debe ejecutarse antes de importar routers que lean
# variables de entorno al cargar módulos.
# ============================================================

load_dotenv()


# ============================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================

def _resolver_nivel_logging() -> int:
    """
    Resuelve el nivel de logging desde la variable de entorno LOG_LEVEL.

    Valores sugeridos:
    - DEBUG
    - INFO
    - WARNING
    - ERROR

    Si LOG_LEVEL no existe o viene inválido, usa INFO por defecto.
    """
    nivel_txt = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, nivel_txt, logging.INFO)


LOG_LEVEL = _resolver_nivel_logging()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,  # Fuerza la configuración aunque Uvicorn ya tenga handlers.
)


# ============================================================
# LOGGERS DE INTERÉS
# ============================================================
# Dejamos estos loggers alineados con LOG_LEVEL para poder ver:
# - llamadas al chat;
# - trazas de búsqueda;
# - errores de routers;
# - errores de servicios;
# - flujo multimodal;
# - oportunidades comerciales.
# ============================================================

for nombre_logger in (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "routers",
    "services",
    "memory",
    "orchestration",
):
    logging.getLogger(nombre_logger).setLevel(LOG_LEVEL)

logger = logging.getLogger(__name__)
logger.info("Logging inicializado en nivel %s", logging.getLevelName(LOG_LEVEL))


# ============================================================
# IMPORTAR ROUTERS DESPUÉS DE load_dotenv()
# ============================================================
# Esto es importante porque algunos módulos leen variables de entorno
# cuando se importan.
#
# Routers actuales:
# - productos: catálogo, health, búsqueda.
# - chat: conversación principal de NIA.
# - uploads: carga de archivos.
# - commercial_opportunities: consulta interna de oportunidades
#   comerciales guardadas por NIA.
# ============================================================

from routers import (  # noqa: E402
    productos,
    chat,
    uploads,
    commercial_opportunities,
)


# ============================================================
# INSTANCIA FASTAPI
# ============================================================
# Esta es la app única del backend.
# Se expone en Swagger en /docs.
# ============================================================

app = FastAPI(
    title="NIA - VIA Industrial",
    description="Asistente comercial inteligente para catálogo industrial",
    version="2.0.0",
)


# ============================================================
# CORS
# ============================================================
# Permite llamadas desde frontend local.
#
# Nota:
# En Azure también puedes manejar CORS desde el portal de App Service.
# Si agregamos nuevos dominios públicos, se pueden sumar aquí o en Azure.
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REGISTRO DE ROUTERS
# ============================================================
# Aquí conectamos los módulos de endpoints al backend.
#
# Importante:
# Cada router debe definir su propio APIRouter.
# main.py solo los registra, no implementa lógica de negocio.
# ============================================================

app.include_router(productos.router)
app.include_router(chat.router)
app.include_router(uploads.router)
app.include_router(commercial_opportunities.router)


# ============================================================
# ENDPOINT RAÍZ
# ============================================================

@app.get("/", include_in_schema=False)
def root():
    """
    Endpoint raíz.
    No aparece en Swagger porque es solo informativo.

    Sirve para comprobar rápidamente que la app está viva.
    """
    return {
        "sistema": "NIA",
        "version": "2.0.0",
        "estado": "activo",
        "docs": "/docs",
        "log_level": logging.getLevelName(LOG_LEVEL),
        "routers": [
            "productos",
            "chat",
            "uploads",
            "commercial_opportunities",
        ],
    }