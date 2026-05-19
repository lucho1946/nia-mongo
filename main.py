# ============================================================
# main.py
# Entrypoint único de la aplicación NIA.
# Este es el archivo que arranca todo — Gunicorn/Uvicorn apunta aquí.
# Solo hace tres cosas:
# 1) configurar logging
# 2) crear la app
# 3) registrar los routers
# ============================================================

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# Carga de variables de entorno
# ============================================================
# En local toma valores desde .env.
# En Azure App Service toma los valores desde Application Settings.
# ============================================================
load_dotenv()


def _resolver_nivel_logging() -> int:
    """
    Resuelve el nivel de logging desde la variable de entorno LOG_LEVEL.

    Valores sugeridos:
    - DEBUG
    - INFO
    - WARNING
    - ERROR

    Si no existe o viene inválido, usa INFO por defecto.
    """
    nivel_txt = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, nivel_txt, logging.INFO)


# ============================================================
# Logging global
# ============================================================
# Dejamos INFO por defecto para ver:
# - chat.input / chat.output
# - decidir_accion.input / output
# - generar_recomendacion.input / output
# - SEARCH_TRACE
# - errores del flujo multimodal
#
# Si en producción quieres bajarlo, cambia LOG_LEVEL=ERROR.
# ============================================================
LOG_LEVEL = _resolver_nivel_logging()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,  # Fuerza la reconfiguración aunque Uvicorn ya haya instalado handlers
)

# Subimos explícitamente los loggers de interés
for nombre_logger in (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "routers",
    "services",
):
    logging.getLogger(nombre_logger).setLevel(LOG_LEVEL)

logger = logging.getLogger(__name__)
logger.info("Logging inicializado en nivel %s", logging.getLevelName(LOG_LEVEL))

# ============================================================
# Importar routers DESPUÉS de load_dotenv()
# Crítico: algunos módulos leen variables de entorno al importarse.
# Si se importan antes del load_dotenv(), en local pueden fallar.
# ============================================================
from routers import productos, chat, uploads  # noqa: E402


# ============================================================
# Instancia única de FastAPI para toda la aplicación.
# title y description aparecen en Swagger (/docs).
# ============================================================
app = FastAPI(
    title="NIA - VIA Industrial",
    description="Asistente comercial inteligente para catálogo industrial",
    version="2.0.0",
)

# ============================================================
# CORS
# ============================================================
# En local permitimos los puertos típicos del frontend.
# Si luego agregas dominio de producción, se puede incluir aquí.
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Registrar routers
# ============================================================
app.include_router(productos.router)
app.include_router(chat.router)
app.include_router(uploads.router)


@app.get("/", include_in_schema=False)
def root():
    """
    Endpoint raíz — no aparece en Swagger.
    Útil para verificar rápido que la app responde.
    """
    return {
        "sistema": "NIA",
        "version": "2.0.0",
        "estado": "activo",
        "docs": "/docs",
        "log_level": logging.getLevelName(LOG_LEVEL),
    }