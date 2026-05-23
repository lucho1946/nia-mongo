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
# - No inventar datos: solo guarda señales claras del usuario.
#
# Este módulo NO hace retrieval.
# Este módulo NO genera respuestas comerciales.
# Este módulo SOLO administra memoria y extracción básica de contexto.
# ============================================================

from __future__ import annotations

import re
import uuid
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ============================================================
# STORAGE TEMPORAL EN MEMORIA
# ============================================================
# En producción esto debe persistirse en MongoDB Atlas,
# colección sessions, con TTL de 30 minutos.
# ============================================================

_SESSIONS: Dict[str, Dict[str, Any]] = {}


# ============================================================
# CONFIGURACIÓN
# ============================================================

MAX_HISTORY_MESSAGES = 30

TECHNICAL_CONTEXT_KEYS = [
    # Identificación / clasificación
    "familia",
    "categoria",
    "subtipo",
    "codigo_producto",
    "referencia",
    "marca",

    # Datos técnicos generales
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

    # Instrumentación / medición
    "salida",
    "presion",
    "temperatura",
    "caudal",
    "nivel",
    "precision",
    "resolucion",

    # Automatización / eléctrico
    "entradas",
    "salidas",
    "comunicacion",
    "fase",

    # Neumática / válvulas
    "tipo_accion",
    "fluido",

    # UPS / energía
    "autonomia",

    # Otros
    "conectividad",
    "lente",
]


# ============================================================
# UTILIDADES INTERNAS
# ============================================================

def _now_iso() -> str:
    """Fecha actual en UTC ISO."""
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
    """Determina si un valor no aporta contexto."""
    return value in [None, "", [], {}]


# ============================================================
# ESTRUCTURA BASE DE SESIÓN
# ============================================================

def _build_empty_session() -> Dict[str, Any]:
    """Estructura estándar de memoria conversacional."""
    now = _now_iso()

    return {
        "session_id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "intent_actual": None,
        "estado": "inicio",
        "technical_questions_asked": 0,
        "history": [],
        "context": {key: None for key in TECHNICAL_CONTEXT_KEYS},
        "filters": {},
        "last_results": [],
        "pending_questions": [],
        "needs_clarification": False,
        "conversation_complete": False,
    }


# ============================================================
# SESIONES
# ============================================================

def create_session() -> Dict[str, Any]:
    """Crea una nueva sesión conversacional."""
    session = _build_empty_session()
    _SESSIONS[session["session_id"]] = deepcopy(session)
    return deepcopy(session)


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Recupera una sesión existente."""
    session = _SESSIONS.get(session_id)
    if not session:
        return None
    return deepcopy(session)


def save_session(session: Dict[str, Any]) -> None:
    """Guarda cambios de una sesión."""
    session["updated_at"] = _now_iso()
    _SESSIONS[session["session_id"]] = deepcopy(session)


def clear_session(session_id: str) -> bool:
    """Elimina sesión completamente."""
    if session_id in _SESSIONS:
        del _SESSIONS[session_id]
        return True
    return False


# ============================================================
# HISTORIAL
# ============================================================

def append_message(session: Dict[str, Any], role: str, content: str) -> Dict[str, Any]:
    """Agrega mensaje al historial conversacional."""
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
    """Registra una respuesta de NIA en el historial."""
    return append_message(session, role="assistant", content=content)


# ============================================================
# CONTEXTO
# ============================================================

def update_context(session: Dict[str, Any], new_context: Dict[str, Any]) -> Dict[str, Any]:
    """Actualiza contexto conversacional sin sobrescribir con vacíos."""
    context = session.get("context", {})

    for key, value in new_context.items():
        if _is_empty(value):
            continue
        context[key] = value

    session["context"] = context
    return session


def reset_technical_context(session: Dict[str, Any], preserve_history: bool = True) -> Dict[str, Any]:
    """
    Limpia contexto técnico cuando cambia el producto/familia.
    Evita contaminación entre consultas.
    """
    session["context"] = {key: None for key in TECHNICAL_CONTEXT_KEYS}
    session["filters"] = {}
    session["last_results"] = []
    session["pending_questions"] = []
    session["needs_clarification"] = False
    session["conversation_complete"] = False
    session["technical_questions_asked"] = 0

    if not preserve_history:
        session["history"] = []

    return session


def get_context(session: Dict[str, Any]) -> Dict[str, Any]:
    """Obtiene contexto técnico actual."""
    return deepcopy(session.get("context", {}))


# ============================================================
# FILTROS Y RESULTADOS
# ============================================================

def update_filters(session: Dict[str, Any], filters: Dict[str, Any]) -> Dict[str, Any]:
    """Actualiza filtros activos para retrieval."""
    current = session.get("filters", {})

    for key, value in filters.items():
        if _is_empty(value):
            continue
        current[key] = value

    session["filters"] = current
    return session


def save_last_results(session: Dict[str, Any], results: List[dict]) -> Dict[str, Any]:
    """Guarda últimos productos encontrados."""
    session["last_results"] = results[:10]
    return session


def get_last_results(session: Dict[str, Any]) -> List[dict]:
    """Recupera últimos resultados."""
    return deepcopy(session.get("last_results", []))


# ============================================================
# INTENCIÓN / ESTADO
# ============================================================

def set_intent(session: Dict[str, Any], intent: str) -> Dict[str, Any]:
    """Actualiza intención activa."""
    session["intent_actual"] = intent
    return session


def get_intent(session: Dict[str, Any]) -> Optional[str]:
    """Obtiene intención activa."""
    return session.get("intent_actual")


def set_state(session: Dict[str, Any], state: str) -> Dict[str, Any]:
    """Actualiza estado conversacional."""
    session["estado"] = state
    return session


# ============================================================
# CUENTA DE PREGUNTAS TÉCNICAS
# ============================================================

def get_technical_questions_asked(session: Dict[str, Any]) -> int:
    """Obtiene cuántas preguntas técnicas ha hecho NIA."""
    try:
        return int(session.get("technical_questions_asked", 0))
    except (TypeError, ValueError):
        return 0


def set_technical_questions_asked(session: Dict[str, Any], value: int) -> Dict[str, Any]:
    """Fija contador de preguntas técnicas."""
    session["technical_questions_asked"] = max(0, int(value))
    return session


def increment_technical_questions(session: Dict[str, Any], step: int = 1) -> Dict[str, Any]:
    """Incrementa contador de preguntas técnicas."""
    current = get_technical_questions_asked(session)
    session["technical_questions_asked"] = current + max(1, int(step))
    return session


def reset_technical_questions(session: Dict[str, Any]) -> Dict[str, Any]:
    """Reinicia contador de preguntas técnicas."""
    session["technical_questions_asked"] = 0
    return session


# ============================================================
# PREGUNTAS PENDIENTES / FLAGS
# ============================================================

def add_pending_question(session: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Agrega pregunta pendiente."""
    pending = session.get("pending_questions", [])

    if question and question not in pending:
        pending.append(question)

    session["pending_questions"] = pending
    return session


def pop_pending_question(session: Dict[str, Any]) -> Optional[str]:
    """Extrae siguiente pregunta pendiente."""
    pending = session.get("pending_questions", [])

    if not pending:
        return None

    question = pending.pop(0)
    session["pending_questions"] = pending
    return question


def set_needs_clarification(session: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """Marca si NIA necesita más contexto."""
    session["needs_clarification"] = value
    return session


def set_conversation_complete(session: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """Marca conversación como completada."""
    session["conversation_complete"] = value
    return session


# ============================================================
# DEBUG
# ============================================================

def list_sessions() -> List[dict]:
    """Lista sesiones activas."""
    return list(_SESSIONS.values())


def get_session_count() -> int:
    """Total sesiones activas."""
    return len(_SESSIONS)


# ============================================================
# EXTRACCIÓN SIMPLE DE CONTEXTO
# ============================================================

def extract_context_from_message(message: str) -> Dict[str, Any]:
    """
    Extrae contexto útil desde un mensaje.
    No inventa: solo guarda señales claras del usuario.
    """
    original = message or ""
    msg = _normalize(original)
    context: Dict[str, Any] = {}

    # --------------------------------------------------------
    # Código / referencia exacta
    # --------------------------------------------------------
    if re.fullmatch(r"p[0-9]{4,}[a-z0-9]*", msg):
        context["codigo_producto"] = original.strip()
        context["referencia"] = original.strip()
        return context

    if re.fullmatch(r"[0-9]{6,}", msg):
        context["codigo_producto"] = original.strip()
        context["referencia"] = original.strip()
        return context

    # --------------------------------------------------------
    # Familia / categoría amplia
    # --------------------------------------------------------
    if any(w in msg for w in ["sensor", "transmisor", "sonda", "detector"]):
        context["familia"] = "sensor"

    elif "motorreductor" in msg:
        context["familia"] = "motorreductor"

    elif "motor" in msg:
        context["familia"] = "motor"

    elif any(w in msg for w in ["variador", "drive", "vfd", "arrancador"]):
        context["familia"] = "variador"

    elif any(w in msg for w in ["plc", "hmi", "controlador logico", "controlador lógico"]):
        context["familia"] = "plc"

    elif any(w in msg for w in ["valvula", "válvula", "electrovalvula", "electroválvula", "cilindro"]):
        context["familia"] = "valvula"

    elif any(w in msg for w in ["termometro", "termómetro", "camara termica", "cámara térmica", "multimetro", "multímetro"]):
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
    if re.search(r"\b\d+(\.\d+)?\s*(v|vac|vca|vdc|vcc)\b", msg):
        context["voltaje"] = original.strip()

    # --------------------------------------------------------
    # Potencia
    # --------------------------------------------------------
    if re.search(r"\b\d+(\.\d+)?\s*(hp|kw|kva|va)\b", msg):
        context["potencia"] = original.strip()

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

        # Si ya veníamos en herramienta, esta medida suele ser torque.
        # Para evitar recomendar "herramientas" genéricas, fijamos subtipo.
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
    - extrae contexto
    - limpia contexto si cambia la familia
    - actualiza intención
    """
    append_message(session, role="user", content=user_message)

    if detected_intent:
        set_intent(session, detected_intent)

    extracted = extract_context_from_message(user_message)

    current_context = session.get("context", {})
    current_family = current_context.get("familia")
    new_family = extracted.get("familia")

    # Si cambia de familia, limpiar filtros técnicos anteriores.
    if new_family and current_family and new_family != current_family:
        reset_technical_context(session, preserve_history=True)

    # Caso especial:
    # Si ya estábamos en herramienta y el usuario responde "200nm",
    # se interpreta como torque de torquímetro.
    if (
        current_context.get("familia") == "herramienta"
        and extracted.get("medida")
        and "nm" in _normalize(extracted.get("medida"))
        and not extracted.get("subtipo")
    ):
        extracted["subtipo"] = "torquimetro"

    update_context(session, extracted)

    if extracted.get("codigo_producto"):
        reset_technical_questions(session)

    return session
