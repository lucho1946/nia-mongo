# ============================================================
# main.py
# Entrypoint único de la aplicación NIA.
# Este es el archivo que arranca todo — Gunicorn apunta aquí.
# Solo hace tres cosas: configurar logging, crear la app,
# registrar los routers. Nada más.
# ============================================================

import logging
from fastapi import FastAPI
from dotenv import load_dotenv

# Carga variables del archivo .env en desarrollo local.
# En Azure esto no hace nada — las variables ya están en
# App Service → Configuration → Application Settings.
load_dotenv()

# Configuración global de logging.
# ERROR en producción para no llenar los logs de Azure.
# Cambia a INFO si necesitas depurar un problema específico.
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

# ============================================================
# Importar routers DESPUÉS de load_dotenv()
# Crítico: los módulos leen variables de entorno al importarse.
# Si se importan antes del load_dotenv(), en local no encuentran
# las credenciales y fallan.
# ============================================================
from routers import productos, chat

# ============================================================
# Instancia única de FastAPI para toda la aplicación.
# title y description aparecen en el Swagger (/docs).
# ============================================================
app = FastAPI(
    title="NIA - VIA Industrial",
    description="Asistente comercial inteligente para catálogo industrial",
    version="0.1.0",
)

# Registrar routers — cada uno aporta sus endpoints a la app.
app.include_router(productos.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
def root():
    """
    Endpoint raíz — no aparece en Swagger (include_in_schema=False).
    Útil para verificar rápido que la app responde.
    """
    return {
        "sistema": "NIA",
        "version": "2.0.0",
        "estado": "activo",
        "docs": "/docs"
    }