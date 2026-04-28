# ============================================================
# routers/productos.py
# Responsabilidad única: endpoints del catálogo de productos.
# No contiene lógica de negocio — solo recibe, delega y retorna.
# Toda la lógica vive en services/search.py y services/mongo.py
#
# ACTUALIZACIÓN v0.1:
# El endpoint /producto/{codigo} fue actualizado para buscar
# por el campo "CODIGO" (mayúscula) que es el nombre exacto
# del campo en MongoDB — coincide con el Excel original.
# Sin este cambio la búsqueda por código exacto no funciona.
# ============================================================

from fastapi import APIRouter, Query, HTTPException
from services.search import buscar_productos, formatear_producto
from services.mongo import get_collection
import logging

logger = logging.getLogger(__name__)

# APIRouter en lugar de FastAPI() — este es el cambio clave.
# El router se registra en main.py, no corre solo.
router = APIRouter(tags=["Productos"])


@router.get("/health")
def health():
    """
    Verifica que la API está viva Y que la base de datos responde.
    Azure usa este endpoint para saber si el servicio está sano.
    Si retorna 503, Azure puede reiniciar el contenedor automáticamente.
    """
    try:
        # find_one con proyección mínima — solo verifica conectividad,
        # no trae datos innecesarios
        get_collection().find_one({}, {"_id": 1})
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        logger.error(f"Health check falló: {e}")
        # 503 = Service Unavailable — semántica correcta cuando la DB no responde
        raise HTTPException(status_code=503, detail="Base de datos no disponible")


@router.get("/resumen")
def resumen():
    """
    Retorna estadísticas básicas del catálogo.
    Útil para verificar que los datos están cargados correctamente
    después de un deploy o una importación.
    """
    try:
        total = get_collection().count_documents({})
        return {
            "total_registros": total,
            "estado": "ok"
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/producto/{codigo}")
def get_producto(codigo: str):
    """
    Búsqueda exacta por código de producto.
    Usa regex con ^ y $ para anclar inicio y fin — evita que
    'ABC' coincida con 'ABC-123' o '1ABC'.
    Case-insensitive con la opción 'i'.

    Campo actualizado: "CODIGO" (mayúscula) — nombre exacto
    del campo en MongoDB que coincide con el Excel original.
    """
    try:
        resultados = list(get_collection().find(
            # CODIGO en mayúscula — nombre exacto del campo en MongoDB
            {"CODIGO": {"$regex": f"^{codigo}$", "$options": "i"}},
            {"_id": 0}
        ))
        return {
            "query": codigo,
            "total_encontrados": len(resultados),
            "resultados": [formatear_producto(p) for p in resultados]
        }
    except Exception as e:
        logger.error(f"Error en /producto/{codigo}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buscar")
def buscar(
    q: str = Query(..., min_length=1, description="Texto libre o código de producto"),
    limit: int = Query(default=10, ge=1, le=50)
):
    """
    Búsqueda inteligente por texto libre.
    Combina filtro MongoDB + scoring RapidFuzz.
    Acepta nombres parciales, marcas, categorías, referencias.
    El parámetro limit controla cuántos resultados retorna (máx 50).
    """
    try:
        resultados = buscar_productos(q, limit=limit)
        return {
            "query": q,
            "total_encontrados": len(resultados),
            "resultados": [formatear_producto(p) for p in resultados]
        }
    except Exception as e:
        logger.error(f"Error en /buscar: {e}")
        raise HTTPException(status_code=500, detail="Error procesando búsqueda")