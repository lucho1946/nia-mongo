# ============================================================
# services/session.py
# Responsabilidad única: gestionar sesiones conversacionales.
#
# QUÉ ES UNA SESIÓN:
# Es la memoria de una conversación activa. Guarda todo lo que
# el cliente ha dicho para que NIA pueda hacer preguntas
# inteligentes y acumular contexto antes de recomendar.
#
# CÓMO FUNCIONA EL TTL:
# Cada sesión tiene un campo expires_at. MongoDB revisa ese campo
# cada 60 segundos y borra automáticamente las sesiones expiradas.
# El índice TTL que creamos en Atlas hace esto sin código adicional.
#
# ANTES DE EXPIRAR:
# El historial completo se guarda en el documento. Si en el futuro
# queremos construir el perfil permanente del cliente, los datos
# ya están disponibles para migrarlos a la colección clientes.
# ============================================================

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from .mongo import get_db
import logging

logger = logging.getLogger(__name__)

# Tiempo de inactividad antes de que la sesión expire
SESSION_TTL_MINUTES = 30


def get_sessions_collection():
    """
    Retorna la colección sessions de MongoDB.
    Centralizado aquí para que si cambia el nombre
    solo se modifica en un lugar.
    """
    return get_db()["sessions"]


def crear_sesion(canal: str = "web", cliente_id: str = "anonimo") -> dict:
    """
    Crea una sesión nueva para un cliente.

    Parámetros:
    - canal: de dónde viene el cliente ('web', 'whatsapp', 'api')
    - cliente_id: identificador del cliente (celular, session web, etc)
      En Fase 1 puede ser 'anonimo'. En Fase 2 será NIT o celular.

    Retorna el documento de sesión con _id como string.
    """
    col = get_sessions_collection()
    ahora = datetime.now(timezone.utc)

    sesion = {
        # Identificación del cliente y canal
        "canal":      canal,
        "cliente_id": cliente_id,

        # Estado del flujo conversacional
        # inicio → recopilando → buscando → completado
        "estado": "inicio",

        # Contexto acumulado durante la conversación
        # Aquí se guardan las respuestas técnicas del cliente
        # Ejemplo: {"voltaje": "220V", "potencia": "5HP"}
        "contexto": {},

        # Historial completo de mensajes
        # Se envía a OpenAI en cada llamada para mantener el contexto
        # Formato: [{"role": "user", "content": "..."}, ...]
        "historial": [],

        # Contador de preguntas hechas por NIA
        # La IA decide cuándo tiene suficiente contexto
        # pero lo registramos para análisis futuro
        "preguntas_hechas": 0,

        # Timestamps
        "created_at": ahora.isoformat(),

        # expires_at es el campo que usa el índice TTL de MongoDB
        # para borrar la sesión automáticamente tras 30 min de inactividad
        "expires_at": ahora + timedelta(minutes=SESSION_TTL_MINUTES),
    }

    resultado = col.insert_one(sesion)
    sesion["_id"] = str(resultado.inserted_id)
    return sesion


def obtener_sesion(session_id: str) -> dict | None:
    """
    Busca una sesión activa por su ID.
    Retorna None si no existe o ya fue borrada por el TTL.
    """
    col = get_sessions_collection()
    try:
        doc = col.find_one({"_id": ObjectId(session_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except Exception:
        # Si el session_id tiene formato inválido retorna None
        return None


def actualizar_sesion(session_id: str, cambios: dict):
    """
    Actualiza campos específicos de una sesión.
    Siempre renueva expires_at para extender la sesión
    cada vez que el cliente interactúa — reset del timer de 30 min.
    """
    col = get_sessions_collection()
    ahora = datetime.now(timezone.utc)

    # Renovar el TTL con cada interacción
    cambios["expires_at"] = ahora + timedelta(minutes=SESSION_TTL_MINUTES)

    col.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": cambios}
    )


def agregar_mensaje(session_id: str, role: str, content: str):
    """
    Agrega un mensaje al historial de la sesión.

    Parámetros:
    - role: 'user' (cliente) o 'assistant' (NIA)
    - content: texto del mensaje

    El historial completo se envía a OpenAI en cada llamada
    para que la IA recuerde toda la conversación.
    """
    col = get_sessions_collection()
    ahora = datetime.now(timezone.utc)

    col.update_one(
        {"_id": ObjectId(session_id)},
        {
            # $push agrega al array sin reemplazarlo
            "$push": {
                "historial": {
                    "role":    role,
                    "content": content
                }
            },
            # Renovar TTL con cada mensaje
            "$set": {
                "expires_at": ahora + timedelta(minutes=SESSION_TTL_MINUTES)
            }
        }
    )


def incrementar_preguntas(session_id: str):
    """
    Incrementa el contador de preguntas hechas por NIA.
    Útil para análisis futuro y para saber cuántas veces
    NIA tuvo que preguntar antes de encontrar el producto.
    """
    col = get_sessions_collection()
    ahora = datetime.now(timezone.utc)

    col.update_one(
        {"_id": ObjectId(session_id)},
        {
            "$inc": {"preguntas_hechas": 1},
            "$set": {"expires_at": ahora + timedelta(minutes=SESSION_TTL_MINUTES)}
        }
    )


def cerrar_sesion(session_id: str):
    """
    Elimina una sesión manualmente antes de que expire.
    El frontend puede llamar esto cuando el cliente cierra el chat.
    En producción con WhatsApp no se usa — el TTL maneja todo.
    """
    col = get_sessions_collection()
    try:
        col.delete_one({"_id": ObjectId(session_id)})
        logger.info(f"Sesión {session_id} cerrada manualmente")
    except Exception as e:
        logger.error(f"Error cerrando sesión {session_id}: {e}")