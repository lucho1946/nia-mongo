# ============================================================
# memory/conversation_memory.py
# ============================================================
# RESPONSABILIDAD:
# Manejo de memoria conversacional de NIA.
#
# Enfoque alineado:
# - Mantener contexto conversacional por sesión.
# - Evitar que el cliente repita información.
# - Acumular datos técnicos útiles antes de buscar.
# - Limpiar contexto cuando el usuario cambia de producto/familia.
# - Detectar códigos exactos aunque vengan dentro de frases.
# - Recordar último producto seleccionado para continuidad comercial.
# - Guardar la última pregunta activa de NIA.
# - Guardar el slot pendiente que el usuario debe responder.
# - Interpretar respuestas cortas según la pregunta anterior.
# - No inventar datos: solo guarda señales claras del usuario.
#
# NOTA PRODUCTIVA:
# Hoy este módulo mantiene memoria en RAM para desarrollo local.
# La versión siguiente debe persistir esta estructura en MongoDB
# con TTL máximo de 8 días:
#
# 8 días = 8 * 24 * 60 * 60 = 691200 segundos
#
# Índice esperado en MongoDB:
# db.sessions.createIndex({ "updated_at": 1 }, { expireAfterSeconds: 691200 })
# ============================================================

from __future__ import annotations

import re
import uuid
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from memory.slot_response_detector import detect_slot_response
from memory.mongo_session_store import (
    save_session_to_mongo,
    get_session_from_mongo,
    delete_session_from_mongo,
)


# ============================================================
# STORAGE TEMPORAL EN MEMORIA
# ============================================================

_SESSIONS: Dict[str, Dict[str, Any]] = {}


# ============================================================
# CONFIGURACIÓN
# ============================================================

MAX_HISTORY_MESSAGES = 30
SESSION_TTL_SECONDS = 691200  # 8 días


# ============================================================
# CAMPOS TÉCNICOS / COMERCIALES PERMITIDOS EN CONTEXTO
# ============================================================
# update_context() solo guarda claves presentes en esta lista.
# Por eso aquí deben existir tanto campos técnicos como banderas
# conversacionales útiles.

TECHNICAL_CONTEXT_KEYS = [
    "familia",
    "categoria",
    "subtipo",
    "codigo_producto",
    "referencia",
    "marca",
    "rango",
    "voltaje",
    "potencia",
    "rpm",
    "corriente",
    "frecuencia",
    "conexion",
    "diametro",
    "medida",
    "material",
    "aplicacion",
    "salida",
    "presion",
    "temperatura",
    "caudal",
    "nivel",
    "precision",
    "resolucion",
    "entradas",
    "salidas",
    "comunicacion",
    "fase",
    "tipo_accion",
    "fluido",
    "autonomia",
    "conectividad",
    "lente",

    # --------------------------------------------------------
    # Flags conversacionales / respuestas negativas
    # --------------------------------------------------------
    "marca_descartada",
    "brand_preference_status",
    "referencia_descartada",
    "reference_status",
    "aplicacion_descartada",
    "application_status",
    "generic_need_status",
]


# ============================================================
# UTILIDADES INTERNAS
# ============================================================

def _now_iso() -> str:
    """
    Fecha actual en UTC ISO.
    """
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: Any) -> str:
    """
    Normaliza texto:
    - minúsculas
    - sin acentos
    - espacios limpios
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )

    return re.sub(r"\s+", " ", text)


def _is_empty(value: Any) -> bool:
    """
    Determina si un valor no aporta contexto.
    """
    return value in [None, "", [], {}]


def extract_exact_product_code(message: str) -> Optional[str]:
    """
    Extrae código de producto aunque venga dentro de una frase.

    Ejemplos:
    - P382280
    - busco el P382280
    - me cotizas el producto P382280
    - producto 300203

    Evita confundir:
    - 220v
    - 3hp
    - 200nm
    """
    raw = str(message or "").strip()

    if not raw:
        return None

    # Código VIA tipo P382280.
    match_p = re.search(
        r"\b(P[0-9]{4,}[A-Za-z0-9]*)\b",
        raw,
        flags=re.IGNORECASE,
    )

    if match_p:
        return match_p.group(1).upper()

    # Código numérico largo.
    # Ejemplo: 300203.
    # Mínimo 6 dígitos para evitar confundir valores técnicos.
    match_num = re.search(r"\b([0-9]{6,})\b", raw)

    if match_num:
        return match_num.group(1)

    return None


# ============================================================
# ESTRUCTURA BASE DE SESIÓN
# ============================================================

def _build_empty_session() -> Dict[str, Any]:
    """
    Estructura estándar de memoria conversacional.
    """
    now = _now_iso()

    return {
        "session_id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "expires_in_seconds": SESSION_TTL_SECONDS,

        # Estado conversacional
        "intent_actual": None,
        "estado": "inicio",
        "technical_questions_asked": 0,

        # Historial y contexto
        "history": [],
        "context": {key: None for key in TECHNICAL_CONTEXT_KEYS},
        "filters": {},

        # Resultados / selección comercial
        "last_results": [],
        "last_selected_product": None,
        "last_selected_product_code": None,
        "estado_negociacion": None,

        # ----------------------------------------------------
        # Última pregunta activa / slot pendiente
        # ----------------------------------------------------
        # Esto permite que NIA entienda respuestas cortas.
        #
        # Ejemplo:
        # NIA: ¿Qué tipo específico necesitas?
        # last_assistant_question_field = "subtipo"
        # Usuario: sensor fotoeléctrico
        # NIA debe guardar subtipo = fotoelectrico
        # ----------------------------------------------------
        "last_assistant_question_field": None,
        "last_assistant_question_text": None,
        "last_assistant_question_at": None,
        "slot_pendiente": None,

        # Flags de conversación
        "pending_questions": [],
        "needs_clarification": False,
        "conversation_complete": False,
    }


# ============================================================
# SESIONES
# ============================================================

def create_session() -> Dict[str, Any]:
    """
    Crea una nueva sesión conversacional.

    Estrategia:
    - Guarda en RAM para desarrollo local.
    - Intenta guardar también en MongoDB para producción/Azure.
    - Si Mongo no está disponible localmente, el sistema sigue vivo.
    """
    session = _build_empty_session()

    # Fallback local en RAM.
    _SESSIONS[session["session_id"]] = deepcopy(session)

    # Persistencia productiva.
    # Si falla, mongo_session_store retorna False y no rompe NIA.
    save_session_to_mongo(session)

    return deepcopy(session)


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Recupera una sesión existente.

    Orden:
    1. RAM local, si existe.
    2. MongoDB, si no está en RAM.

    Esto permite:
    - Desarrollo local rápido.
    - Producción en Azure con múltiples workers.
    """
    session_id = str(session_id or "").strip()

    if not session_id:
        return None

    # 1. Intento rápido en RAM.
    session = _SESSIONS.get(session_id)

    if session:
        return deepcopy(session)

    # 2. Fallback productivo desde MongoDB.
    mongo_session = get_session_from_mongo(session_id)

    if mongo_session:
        # Rehidrata RAM del worker actual para próximas llamadas.
        _SESSIONS[session_id] = deepcopy(mongo_session)
        return deepcopy(mongo_session)

    return None


def save_session(session: Dict[str, Any]) -> None:
    """
    Guarda cambios de una sesión.

    Guarda en:
    - RAM: fallback local.
    - MongoDB: persistencia real para Azure.

    MongoDB es necesario para conservar:
    - último producto seleccionado
    - slot pendiente
    - última pregunta
    - historial
    - contexto técnico
    entre requests y workers distintos.
    """
    if not isinstance(session, dict):
        return

    session_id = session.get("session_id")

    if not session_id:
        return

    session["updated_at"] = _now_iso()
    session["expires_in_seconds"] = SESSION_TTL_SECONDS

    # Fallback local.
    _SESSIONS[session_id] = deepcopy(session)

    # Persistencia productiva.
    save_session_to_mongo(session)


def clear_session(session_id: str) -> bool:
    """
    Elimina sesión completamente.

    Borra tanto de RAM como de MongoDB.
    """
    session_id = str(session_id or "").strip()

    if not session_id:
        return False

    removed = False

    if session_id in _SESSIONS:
        del _SESSIONS[session_id]
        removed = True

    mongo_removed = delete_session_from_mongo(session_id)

    return removed or mongo_removed


# ============================================================
# HISTORIAL
# ============================================================

def append_message(session: Dict[str, Any], role: str, content: str) -> Dict[str, Any]:
    """
    Agrega mensaje al historial conversacional.
    """
    history = session.get("history", [])

    history.append({
        "role": role,
        "content": content,
        "timestamp": _now_iso(),
    })

    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]

    session["history"] = history
    session["updated_at"] = _now_iso()

    return session


def append_assistant_message(session: Dict[str, Any], content: str) -> Dict[str, Any]:
    """
    Registra una respuesta de NIA en el historial.
    """
    return append_message(session, role="assistant", content=content)


# ============================================================
# CONTEXTO
# ============================================================

def update_context(session: Dict[str, Any], new_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Actualiza contexto conversacional sin sobrescribir con vacíos.
    """
    context = session.get("context", {})

    for key, value in new_context.items():
        if _is_empty(value):
            continue

        if key in TECHNICAL_CONTEXT_KEYS:
            context[key] = value

    session["context"] = context
    return session


def get_context(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene contexto técnico actual.
    """
    return deepcopy(session.get("context", {}))


# ============================================================
# ÚLTIMA PREGUNTA / SLOT PENDIENTE
# ============================================================

def set_last_assistant_question(
    session: Dict[str, Any],
    field: Optional[str],
    question: str,
) -> Dict[str, Any]:
    """
    Guarda cuál fue la última pregunta que hizo NIA
    y qué campo intentaba llenar.

    Ejemplo:
    - field = "subtipo"
    - question = "¿Qué tipo específico necesitas?"
    """
    session["last_assistant_question_field"] = field
    session["last_assistant_question_text"] = question
    session["last_assistant_question_at"] = _now_iso()
    session["slot_pendiente"] = field

    return session


def clear_last_assistant_question(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Limpia última pregunta activa.
    Se usa cuando el usuario ya respondió el slot pendiente
    o cuando NIA recomienda / completa la conversación.
    """
    session["last_assistant_question_field"] = None
    session["last_assistant_question_text"] = None
    session["last_assistant_question_at"] = None
    session["slot_pendiente"] = None

    return session


def get_last_assistant_question_field(session: Dict[str, Any]) -> Optional[str]:
    """
    Devuelve el campo de la última pregunta activa.
    """
    return session.get("last_assistant_question_field") or session.get("slot_pendiente")


def reset_technical_context(
    session: Dict[str, Any],
    preserve_history: bool = True,
    preserve_selected_product: bool = True,
) -> Dict[str, Any]:
    """
    Limpia contexto técnico cuando cambia el producto/familia.

    preserve_selected_product:
    - True: mantiene último producto para continuidad comercial.
    - False: limpia también selección comercial.
    """
    session["context"] = {key: None for key in TECHNICAL_CONTEXT_KEYS}
    session["filters"] = {}
    session["pending_questions"] = []
    session["needs_clarification"] = False
    session["conversation_complete"] = False
    session["technical_questions_asked"] = 0

    clear_last_assistant_question(session)

    if not preserve_selected_product:
        session["last_results"] = []
        session["last_selected_product"] = None
        session["last_selected_product_code"] = None
        session["estado_negociacion"] = None

    if not preserve_history:
        session["history"] = []

    return session


# ============================================================
# FILTROS Y RESULTADOS
# ============================================================

def update_filters(session: Dict[str, Any], filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Actualiza filtros activos para retrieval.
    """
    current = session.get("filters", {})

    for key, value in filters.items():
        if _is_empty(value):
            continue

        current[key] = value

    session["filters"] = current
    return session


def _normalize_product_for_memory(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza un producto para guardarlo como selección comercial.

    Mantiene el documento original lo suficiente para que response_engine
    pueda crear cards, pero agrega campos estándar.
    """
    if not isinstance(product, dict):
        return {}

    codigo = (
        product.get("codigo")
        or product.get("CODIGO")
        or ""
    )

    nombre = (
        product.get("nombre")
        or product.get("DESCRIPCION_CORTA_PRE")
        or product.get("descripcion")
        or ""
    )

    marca = (
        product.get("marca")
        or product.get("MARCA_LET")
        or ""
    )

    referencia = (
        product.get("referencia")
        or product.get("REFERENCIA")
        or ""
    )

    normalized = deepcopy(product)

    normalized["codigo"] = str(codigo).strip()
    normalized["nombre"] = str(nombre).strip()
    normalized["marca"] = str(marca).strip()
    normalized["referencia"] = str(referencia).strip()

    return normalized


def save_last_results(session: Dict[str, Any], results: List[dict]) -> Dict[str, Any]:
    """
    Guarda últimos productos encontrados.

    Si hay al menos un resultado, también guarda el primer producto como
    last_selected_product para continuidad comercial.
    """
    safe_results = results[:10] if isinstance(results, list) else []
    session["last_results"] = deepcopy(safe_results)

    if safe_results:
        set_last_selected_product(session, safe_results[0])

    return session


def get_last_results(session: Dict[str, Any]) -> List[dict]:
    """
    Recupera últimos resultados.
    """
    return deepcopy(session.get("last_results", []))


def set_last_selected_product(
    session: Dict[str, Any],
    product: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Guarda el último producto seleccionado por NIA/usuario.

    Esta es la pieza clave para:
    - "Quiero cotizar este producto"
    - "Envíame una cotización"
    - "Lo quiero"
    - "Solicitar cotización"
    """
    normalized = _normalize_product_for_memory(product)

    if not normalized:
        return session

    codigo = normalized.get("codigo") or normalized.get("CODIGO")

    session["last_selected_product"] = normalized
    session["last_selected_product_code"] = str(codigo or "").strip() or None
    session["estado_negociacion"] = "producto_seleccionado"

    return session


def get_last_selected_product(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Recupera último producto seleccionado.

    Si no existe last_selected_product, intenta usar el primer last_result.
    """
    selected = session.get("last_selected_product")

    if isinstance(selected, dict) and selected:
        return deepcopy(selected)

    last_results = session.get("last_results", [])

    if isinstance(last_results, list) and last_results:
        first = last_results[0]

        if isinstance(first, dict):
            return deepcopy(first)

    return None


# ============================================================
# INTENCIÓN / ESTADO
# ============================================================

def set_intent(session: Dict[str, Any], intent: str) -> Dict[str, Any]:
    """
    Actualiza intención activa.
    """
    session["intent_actual"] = intent
    return session


def get_intent(session: Dict[str, Any]) -> Optional[str]:
    """
    Obtiene intención activa.
    """
    return session.get("intent_actual")


def set_state(session: Dict[str, Any], state: str) -> Dict[str, Any]:
    """
    Actualiza estado conversacional.
    """
    session["estado"] = state
    return session


# ============================================================
# CUENTA DE PREGUNTAS TÉCNICAS
# ============================================================

def get_technical_questions_asked(session: Dict[str, Any]) -> int:
    """
    Obtiene cuántas preguntas técnicas ha hecho NIA.
    """
    try:
        return int(session.get("technical_questions_asked", 0))
    except (TypeError, ValueError):
        return 0


def set_technical_questions_asked(session: Dict[str, Any], value: int) -> Dict[str, Any]:
    """
    Fija contador de preguntas técnicas.
    """
    session["technical_questions_asked"] = max(0, int(value))
    return session


def increment_technical_questions(session: Dict[str, Any], step: int = 1) -> Dict[str, Any]:
    """
    Incrementa contador de preguntas técnicas.
    """
    current = get_technical_questions_asked(session)
    session["technical_questions_asked"] = current + max(1, int(step))
    return session


def reset_technical_questions(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reinicia contador de preguntas técnicas.
    """
    session["technical_questions_asked"] = 0
    return session


# ============================================================
# PREGUNTAS PENDIENTES / FLAGS
# ============================================================

def add_pending_question(session: Dict[str, Any], question: str) -> Dict[str, Any]:
    """
    Agrega pregunta pendiente.
    """
    pending = session.get("pending_questions", [])

    if question and question not in pending:
        pending.append(question)

    session["pending_questions"] = pending
    return session


def pop_pending_question(session: Dict[str, Any]) -> Optional[str]:
    """
    Extrae siguiente pregunta pendiente.
    """
    pending = session.get("pending_questions", [])

    if not pending:
        return None

    question = pending.pop(0)
    session["pending_questions"] = pending

    return question


def set_needs_clarification(session: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """
    Marca si NIA necesita más contexto.
    """
    session["needs_clarification"] = value
    return session


def set_conversation_complete(session: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """
    Marca conversación como completada.
    """
    session["conversation_complete"] = value
    return session


# ============================================================
# DEBUG
# ============================================================

def list_sessions() -> List[dict]:
    """
    Lista sesiones activas.
    """
    return list(_SESSIONS.values())


def get_session_count() -> int:
    """
    Total sesiones activas.
    """
    return len(_SESSIONS)


# ============================================================
# EXTRACCIÓN SIMPLE DE CONTEXTO
# ============================================================

def extract_context_from_message(message: str) -> Dict[str, Any]:
    """
    Extrae contexto útil desde un mensaje.

    No inventa:
    solo guarda señales claras que el usuario escribió.
    """
    original = message or ""
    msg = _normalize(original)
    context: Dict[str, Any] = {}

    # --------------------------------------------------------
    # Código / referencia exacta dentro de frase
    # --------------------------------------------------------
    exact_code = extract_exact_product_code(original)

    if exact_code:
        context["codigo_producto"] = exact_code
        context["referencia"] = exact_code
        return context

    # --------------------------------------------------------
    # Familia / categoría amplia
    # --------------------------------------------------------
    if any(w in msg for w in ["sensor", "sensores", "transmisor", "sonda", "detector"]):
        context["familia"] = "sensor"

    elif "motorreductor" in msg or "motor reductor" in msg:
        context["familia"] = "motorreductor"

    elif any(w in msg for w in ["variador", "variadores", "drive", "vfd", "arrancador", "inversor de frecuencia"]):
        context["familia"] = "variador"

    elif "motor" in msg:
        context["familia"] = "motor"

    elif any(w in msg for w in ["plc", "hmi", "controlador logico", "controlador lógico"]):
        context["familia"] = "plc"

    elif any(w in msg for w in ["valvula", "valvulas", "válvula", "válvulas", "electrovalvula", "electroválvula", "cilindro"]):
        context["familia"] = "valvula"

    elif any(w in msg for w in ["termometro", "termómetro", "camara termica", "cámara térmica", "multimetro", "multímetro", "anemometro", "anemómetro"]):
        context["familia"] = "medicion"

    elif any(w in msg for w in ["ups", "nobreak", "no break"]):
        context["familia"] = "ups"

    elif any(w in msg for w in ["torquimetro", "torquímetro"]):
        context["familia"] = "herramienta"
        context["subtipo"] = "torquimetro"

    elif any(w in msg for w in ["herramienta", "taladro", "esmeril", "llave"]):
        context["familia"] = "herramienta"

    elif any(w in msg for w in ["breaker", "contactor", "rele", "relé", "fuente", "guardamotor"]):
        context["familia"] = "electrico"

    # --------------------------------------------------------
    # Subtipos de sensores industriales
    # --------------------------------------------------------
    if any(w in msg for w in ["fotoelectrico", "foto electrico", "fotocelda", "foto celda"]):
        context["familia"] = "sensor"
        context["subtipo"] = "fotoelectrico"

    if any(w in msg for w in ["inductivo", "proximidad inductiva", "proximidad inductivo"]):
        context["familia"] = "sensor"
        context["subtipo"] = "inductivo"

    if any(w in msg for w in ["capacitivo", "proximidad capacitiva", "proximidad capacitivo"]):
        context["familia"] = "sensor"
        context["subtipo"] = "capacitivo"

    if any(w in msg for w in ["reflectivo", "retroreflectivo", "retro reflectivo"]):
        context["familia"] = "sensor"
        context["subtipo"] = "reflectivo"

    if any(w in msg for w in ["barrera", "emisor receptor", "emisor y receptor"]):
        context["familia"] = "sensor"
        context["subtipo"] = "barrera"

    if any(w in msg for w in ["difuso", "difusa"]):
        context["familia"] = "sensor"
        context["subtipo"] = "difuso"

    # --------------------------------------------------------
    # Subtipo / aplicación técnica
    # --------------------------------------------------------
    if "presion" in msg or "presión" in msg:
        context["subtipo"] = "presion"
        context["presion"] = original.strip()

    if "temperatura" in msg:
        context["subtipo"] = "temperatura"
        context["temperatura"] = original.strip()

    if "nivel" in msg:
        context["subtipo"] = "nivel"
        context["nivel"] = original.strip()

    if "caudal" in msg:
        context["subtipo"] = "caudal"
        context["caudal"] = original.strip()

    # --------------------------------------------------------
    # Marca
    # --------------------------------------------------------
    known_brands = [
        "siemens", "ifm", "abb", "festo", "smc", "omron",
        "autonics", "pixsys", "ema", "weg", "schneider",
        "danfoss", "yaskawa", "camozzi", "norgren", "parker",
        "dayton", "proto", "black-decker", "cool-line", "horiba",
        "fluke", "honeywell", "allen bradley", "rockwell",
        "xinje", "array", "lutron",
    ]

    for brand in known_brands:
        if brand in msg:
            context["marca"] = brand
            break

    # --------------------------------------------------------
    # Rangos / presión / temperatura
    # --------------------------------------------------------
    if re.search(r"[-+]?\d+(\.\d+)?\s*(a|-|~)\s*[-+]?\d+(\.\d+)?\s*(bar|psi|kpa|mpa|c|°c)", msg):
        context["rango"] = original.strip()

    elif re.search(r"\b\d+(\.\d+)?\s*(bar|psi|kpa|mpa|c|°c)\b", msg):
        context["rango"] = original.strip()

    # --------------------------------------------------------
    # Voltaje
    # --------------------------------------------------------
    voltaje_match = re.search(r"\b\d+(\.\d+)?\s*(v|vac|vca|vdc|vcc)\b", msg)
    if voltaje_match:
        context["voltaje"] = voltaje_match.group(0)

    # --------------------------------------------------------
    # Potencia
    # --------------------------------------------------------
    potencia_match = re.search(r"\b\d+(\.\d+)?\s*(hp|kw|kva|va)\b", msg)
    if potencia_match:
        context["potencia"] = potencia_match.group(0)

    # --------------------------------------------------------
    # RPM
    # --------------------------------------------------------
    if re.search(r"\b\d+(\.\d+)?\s*rpm\b", msg):
        context["rpm"] = original.strip()

    # --------------------------------------------------------
    # Corriente
    # --------------------------------------------------------
    if re.search(r"\b\d+(\.\d+)?\s*a\b", msg):
        context["corriente"] = original.strip()

    # --------------------------------------------------------
    # Entradas / salidas PLC
    # --------------------------------------------------------
    match_entradas = re.search(r"\b(\d+)\s*entradas?\b", msg)
    if match_entradas:
        context["entradas"] = match_entradas.group(1)

    match_salidas = re.search(r"\b(\d+)\s*salidas?\b", msg)
    if match_salidas:
        context["salidas"] = match_salidas.group(1)

    # --------------------------------------------------------
    # Comunicación
    # --------------------------------------------------------
    if any(w in msg for w in ["modbus", "ethernet", "rs485", "rs232", "profibus", "profinet", "usb", "wifi", "wi-fi"]):
        context["comunicacion"] = original.strip()

    # --------------------------------------------------------
    # Salida sensor / señal
    # --------------------------------------------------------
    if any(w in msg for w in ["pnp", "npn", "4-20", "4 20", "0-10v", "0 10v", "analogica", "analógica"]):
        context["salida"] = original.strip()

    # --------------------------------------------------------
    # Válvulas / neumática
    # --------------------------------------------------------
    if "neumatic" in msg or "neumatico" in msg or "neumatica" in msg:
        context["tipo_accion"] = "neumatica"

    elif "electrica" in msg or "electrico" in msg:
        if "valv" in msg:
            context["tipo_accion"] = "electrica"

    elif "manual" in msg:
        context["tipo_accion"] = "manual"

    if re.search(r"\b\d+/\d+\b", msg) or '"' in original or "'" in original:
        context["diametro"] = original.strip()
        context["medida"] = original.strip()

    # --------------------------------------------------------
    # Medida / torque / capacidad
    # --------------------------------------------------------
    if re.search(r"\b\d+(\.\d+)?\s*(nm|n.m|n-m)\b", msg):
        context["medida"] = original.strip()

        if context.get("familia") == "herramienta" or "torquimetro" in msg:
            context["subtipo"] = "torquimetro"

    elif re.search(r"\b\d+(\.\d+)?\s*(mm|cm|m|kg|ton|lb)\b", msg):
        context["medida"] = original.strip()

    # --------------------------------------------------------
    # Aplicación explícita
    # --------------------------------------------------------
    if any(w in msg for w in ["para ", "aplicacion", "aplicación", "uso", "trabajo"]):
        context["aplicacion"] = original.strip()

    return context


# ============================================================
# PIPELINE SIMPLE DE MEMORIA
# ============================================================

def process_memory_update(
    session: Dict[str, Any],
    user_message: str,
    detected_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pipeline básico de memoria:
    - guarda mensaje
    - revisa si responde a un slot pendiente
    - extrae contexto
    - limpia contexto si cambia la familia
    - limpia contexto si llega un código exacto nuevo
    - actualiza intención
    """
    append_message(session, role="user", content=user_message)

    if detected_intent:
        set_intent(session, detected_intent)

    current_context = session.get("context", {})

    # --------------------------------------------------------
    # Primero intentamos interpretar el mensaje como respuesta
    # a la última pregunta activa de NIA.
    #
    # Ejemplo:
    # - NIA preguntó: ¿Qué tipo específico necesitas?
    # - slot_pendiente: subtipo
    # - Usuario: sensor fotoeléctrico
    # - Resultado: subtipo = fotoelectrico
    # --------------------------------------------------------
    pending_slot = get_last_assistant_question_field(session)

    slot_detection = detect_slot_response(
        message=user_message,
        pending_slot=pending_slot,
        previous_context=current_context,
    )

    extracted = extract_context_from_message(user_message)

    if slot_detection.get("matched"):
        slot_context = slot_detection.get("context", {})

        # La respuesta al slot tiene prioridad sobre extracción general.
        extracted = {
            **extracted,
            **slot_context,
        }

        if slot_detection.get("clear_pending_slot"):
            clear_last_assistant_question(session)

    current_context = session.get("context", {})
    current_family = current_context.get("familia")
    new_family = extracted.get("familia")

    # --------------------------------------------------------
    # Caso prioritario: código exacto.
    # --------------------------------------------------------
    # Si el usuario escribe "busco el P382280" o "Perdón es el 300203",
    # ese código manda por encima de cualquier contexto anterior.
    # Conservamos last_selected_product hasta que el orquestador confirme
    # el nuevo producto encontrado.
    # --------------------------------------------------------
    if extracted.get("codigo_producto"):
        reset_technical_context(
            session,
            preserve_history=True,
            preserve_selected_product=True,
        )
        update_context(session, extracted)
        reset_technical_questions(session)
        return session

    # --------------------------------------------------------
    # Si el usuario ahora habla de una familia de producto,
    # y la memoria venía de un código exacto anterior, limpiamos
    # ese código para evitar contaminación.
    # --------------------------------------------------------
    if new_family and current_context.get("codigo_producto"):
        reset_technical_context(
            session,
            preserve_history=True,
            preserve_selected_product=True,
        )
        current_context = session.get("context", {})
        current_family = current_context.get("familia")

    # --------------------------------------------------------
    # Si cambia de familia, limpiar filtros técnicos anteriores.
    # --------------------------------------------------------
    if new_family and current_family and new_family != current_family:
        reset_technical_context(
            session,
            preserve_history=True,
            preserve_selected_product=False,
        )

    # --------------------------------------------------------
    # Caso especial:
    # Si ya estábamos en herramienta y el usuario responde "200nm",
    # se interpreta como torque de torquímetro.
    # --------------------------------------------------------
    if (
        current_context.get("familia") == "herramienta"
        and extracted.get("medida")
        and "nm" in _normalize(extracted.get("medida"))
        and not extracted.get("subtipo")
    ):
        extracted["familia"] = "herramienta"
        extracted["subtipo"] = "torquimetro"

    update_context(session, extracted)

    return session