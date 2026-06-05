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
# - Detectar códigos exactos aunque vengan dentro de frases.
# - Recordar último producto seleccionado para continuidad comercial.
# - Guardar la última pregunta activa de NIA.
# - Guardar el slot pendiente que el usuario debe responder.
# - Interpretar respuestas cortas según la pregunta anterior.
# - No inventar datos: solo guarda señales claras del usuario.
#
# Reglas nuevas:
# - Este módulo NO clasifica por familias manuales.
# - Este módulo NO usa marcas hardcodeadas.
# - Este módulo NO asigna subtipos por listas manuales.
# - OpenAI + NIA OS + catálogo real se encargan de interpretación semántica.
# - La memoria solo guarda datos explícitos del usuario.
#
# NOTA PRODUCTIVA:
# En local puede funcionar con RAM.
# En Azure debe persistir en MongoDB con TTL de 8 días.
#
# 8 días = 8 * 24 * 60 * 60 = 691200 segundos
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
#
# Nota:
# Conservamos campos legacy como familia/categoria/subtipo por contrato
# con frontend, response engine o consumidores antiguos, pero este módulo
# ya NO los llena mediante listas manuales.
# ============================================================

COMMERCIAL_DATA_KEYS = [
    "nombre_cliente",
    "empresa",
    "correo",
    "telefono",
    "cantidad",
    "presupuesto_aproximado",
    "fecha_estimada_compra",
]

TECHNICAL_CONTEXT_KEYS = [
    # --------------------------------------------------------
    # Legacy / compatibilidad
    # --------------------------------------------------------
    "familia",
    "categoria",
    "subtipo",

    # --------------------------------------------------------
    # Identificadores exactos
    # --------------------------------------------------------
    "codigo_producto",
    "referencia",
    "marca",

    # --------------------------------------------------------
    # Datos técnicos objetivos
    # --------------------------------------------------------
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
    "technical_clarification",
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
    - minúsculas;
    - sin acentos;
    - espacios limpios.
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text).strip()


def _safe_text(value: Any) -> str:
    """
    Convierte cualquier valor a texto seguro.
    """
    if value in [None, "", [], {}]:
        return ""

    try:
        return str(value).strip()
    except Exception:
        return ""


def _is_empty(value: Any) -> bool:
    """
    Determina si un valor no aporta contexto.
    """
    return value in [None, "", [], {}]


def _store_original_if_match(
    context: Dict[str, Any],
    key: str,
    pattern: str,
    normalized_message: str,
    original_message: str,
    *,
    flags: int = 0,
) -> None:
    """
    Guarda el mensaje original en un campo si hay match.
    """
    if re.search(pattern, normalized_message, flags=flags):
        context[key] = original_message.strip()


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

        # Datos comerciales estructurados
        "commercial_data": {key: None for key in COMMERCIAL_DATA_KEYS},

        # Última pregunta activa / slot pendiente
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

    _SESSIONS[session["session_id"]] = deepcopy(session)

    save_session_to_mongo(session)

    return deepcopy(session)


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Recupera una sesión existente.

    Orden:
    1. RAM local, si existe.
    2. MongoDB, si no está en RAM.
    """
    session_id = str(session_id or "").strip()

    if not session_id:
        return None

    session = _SESSIONS.get(session_id)

    if session:
        return deepcopy(session)

    mongo_session = get_session_from_mongo(session_id)

    if mongo_session:
        _SESSIONS[session_id] = deepcopy(mongo_session)
        return deepcopy(mongo_session)

    return None


def save_session(session: Dict[str, Any]) -> None:
    """
    Guarda cambios de una sesión.

    Guarda en:
    - RAM: fallback local.
    - MongoDB: persistencia real para Azure.
    """
    if not isinstance(session, dict):
        return

    session_id = session.get("session_id")

    if not session_id:
        return

    session["updated_at"] = _now_iso()
    session["expires_in_seconds"] = SESSION_TTL_SECONDS

    _SESSIONS[session_id] = deepcopy(session)

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

    history.append(
        {
            "role": role,
            "content": content,
            "timestamp": _now_iso(),
        }
    )

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
    if not isinstance(new_context, dict):
        return session

    context = session.get("context", {})

    if not isinstance(context, dict):
        context = {key: None for key in TECHNICAL_CONTEXT_KEYS}

    # Asegura que nuevas claves existan en sesiones antiguas.
    for key in TECHNICAL_CONTEXT_KEYS:
        context.setdefault(key, None)

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
    context = session.get("context", {})

    if not isinstance(context, dict):
        context = {}

    normalized_context = {key: context.get(key) for key in TECHNICAL_CONTEXT_KEYS}

    return deepcopy(normalized_context)


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
    """
    session["last_assistant_question_field"] = field
    session["last_assistant_question_text"] = question
    session["last_assistant_question_at"] = _now_iso()
    session["slot_pendiente"] = field

    return session


def clear_last_assistant_question(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Limpia última pregunta activa.
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


def get_last_assistant_question_text(session: Dict[str, Any]) -> Optional[str]:
    """
    Devuelve el texto de la última pregunta activa.
    """
    return session.get("last_assistant_question_text")


def reset_technical_context(
    session: Dict[str, Any],
    preserve_history: bool = True,
    preserve_selected_product: bool = True,
) -> Dict[str, Any]:
    """
    Limpia contexto técnico.

    Nota:
    Ya no se usa por cambio de familia manual.
    Se usa cuando llega código exacto nuevo o cuando el flujo comercial
    decide reiniciar explícitamente el contexto.
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
    if not isinstance(filters, dict):
        return session

    current = session.get("filters", {})

    if not isinstance(current, dict):
        current = {}

    for key, value in filters.items():
        if _is_empty(value):
            continue

        current[key] = value

    session["filters"] = current
    return session


def _normalize_product_for_memory(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza un producto para guardarlo como selección comercial.
    """
    if not isinstance(product, dict):
        return {}

    codigo = product.get("codigo") or product.get("CODIGO") or ""
    nombre = (
        product.get("nombre")
        or product.get("NOMBRE_PRODUCTO")
        or product.get("DESCRIPCION_CORTA_PRE")
        or product.get("descripcion")
        or ""
    )
    marca = product.get("marca") or product.get("MARCA_LET") or ""
    referencia = product.get("referencia") or product.get("REFERENCIA") or ""

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
# DATOS COMERCIALES
# ============================================================

def get_commercial_data(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene datos comerciales estructurados de la sesión.
    """
    data = session.get("commercial_data")

    if not isinstance(data, dict):
        data = {}

    normalized = {}

    for key in COMMERCIAL_DATA_KEYS:
        normalized[key] = data.get(key)

    return deepcopy(normalized)


def update_commercial_data(
    session: Dict[str, Any],
    new_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Actualiza datos comerciales sin sobrescribir con vacíos.
    """
    if not isinstance(new_data, dict):
        return session

    current = get_commercial_data(session)

    for key in COMMERCIAL_DATA_KEYS:
        value = new_data.get(key)

        if _is_empty(value):
            continue

        current[key] = value

    session["commercial_data"] = current
    session["updated_at"] = _now_iso()

    return session


def clear_commercial_data(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Limpia datos comerciales estructurados.
    """
    session["commercial_data"] = {key: None for key in COMMERCIAL_DATA_KEYS}
    session["updated_at"] = _now_iso()
    return session


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

    if not isinstance(pending, list):
        pending = []

    if question and question not in pending:
        pending.append(question)

    session["pending_questions"] = pending
    return session


def pop_pending_question(session: Dict[str, Any]) -> Optional[str]:
    """
    Extrae siguiente pregunta pendiente.
    """
    pending = session.get("pending_questions", [])

    if not isinstance(pending, list) or not pending:
        return None

    question = pending.pop(0)
    session["pending_questions"] = pending

    return question


def set_needs_clarification(session: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """
    Marca si NIA necesita más contexto.
    """
    session["needs_clarification"] = bool(value)
    return session


def set_conversation_complete(session: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """
    Marca conversación como completada.
    """
    session["conversation_complete"] = bool(value)
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
    Extrae contexto objetivo desde un mensaje.

    Este extractor NO interpreta familias, marcas ni subtipos por listas
    manuales.

    Solo guarda datos explícitos como:
    - código exacto;
    - rangos y unidades;
    - voltaje;
    - potencia;
    - rpm;
    - corriente;
    - entradas/salidas;
    - protocolos de comunicación explícitos;
    - señales de salida explícitas;
    - diámetro/medida;
    - aplicación textual si el usuario la expresa.
    """
    original = _safe_text(message)
    msg = _normalize(original)
    context: Dict[str, Any] = {}

    if not original:
        return context

    # --------------------------------------------------------
    # Código / referencia exacta dentro de frase
    # --------------------------------------------------------
    exact_code = extract_exact_product_code(original)

    if exact_code:
        context["codigo_producto"] = exact_code
        context["referencia"] = exact_code
        return context

    # --------------------------------------------------------
    # Rangos / presión / temperatura / medidas con unidades
    # --------------------------------------------------------
    range_pattern = (
        r"[-+]?\d+(\.\d+)?\s*(a|-|~)\s*"
        r"[-+]?\d+(\.\d+)?\s*"
        r"(bar|psi|kpa|mpa|pa|c|°c|f|°f|m|cm|mm|metros|metro|ft|pies|kg|g|ton|lb|nm|n\.m|n-m)"
    )

    single_value_pattern = (
        r"\b\d+(\.\d+)?\s*"
        r"(bar|psi|kpa|mpa|pa|c|°c|f|°f|m|cm|mm|metros|metro|ft|pies|kg|g|ton|lb|nm|n\.m|n-m)\b"
    )

    if re.search(range_pattern, msg):
        context["rango"] = original
        context["medida"] = original

    elif re.search(single_value_pattern, msg):
        context["medida"] = original

        if re.search(r"\b(bar|psi|kpa|mpa|pa)\b", msg):
            context["presion"] = original
            context["rango"] = original

        if re.search(r"\b(c|°c|f|°f)\b", msg):
            context["temperatura"] = original
            context["rango"] = original

    # --------------------------------------------------------
    # Voltaje
    # --------------------------------------------------------
    voltaje_match = re.search(r"\b\d+(\.\d+)?\s*(v|vac|vca|vdc|vcc)\b", msg)

    if voltaje_match:
        context["voltaje"] = voltaje_match.group(0)

    # --------------------------------------------------------
    # Potencia
    # --------------------------------------------------------
    potencia_match = re.search(r"\b\d+(\.\d+)?\s*(hp|kw|kva|va|w)\b", msg)

    if potencia_match:
        context["potencia"] = potencia_match.group(0)

    # --------------------------------------------------------
    # RPM
    # --------------------------------------------------------
    if re.search(r"\b\d+(\.\d+)?\s*rpm\b", msg):
        context["rpm"] = original

    # --------------------------------------------------------
    # Corriente
    # --------------------------------------------------------
    corriente_match = re.search(r"\b\d+(\.\d+)?\s*(a|amp|amperios?)\b", msg)

    if corriente_match:
        context["corriente"] = corriente_match.group(0)

    # --------------------------------------------------------
    # Frecuencia
    # --------------------------------------------------------
    frecuencia_match = re.search(r"\b\d+(\.\d+)?\s*(hz|khz|mhz)\b", msg)

    if frecuencia_match:
        context["frecuencia"] = frecuencia_match.group(0)

    # --------------------------------------------------------
    # Entradas / salidas PLC o módulos
    # --------------------------------------------------------
    match_entradas = re.search(r"\b(\d+)\s*entradas?\b", msg)

    if match_entradas:
        context["entradas"] = match_entradas.group(1)

    match_salidas = re.search(r"\b(\d+)\s*salidas?\b", msg)

    if match_salidas:
        context["salidas"] = match_salidas.group(1)

    # --------------------------------------------------------
    # Comunicación explícita
    # --------------------------------------------------------
    communication_terms = [
        "modbus",
        "ethernet",
        "ethernet/ip",
        "rs485",
        "rs-485",
        "rs232",
        "rs-232",
        "profibus",
        "profinet",
        "usb",
        "wifi",
        "wi-fi",
        "bluetooth",
        "canopen",
        "hart",
        "fieldbus",
    ]

    if any(term in msg for term in communication_terms):
        context["comunicacion"] = original

    # --------------------------------------------------------
    # Señal / salida explícita
    # --------------------------------------------------------
    output_terms = [
        "pnp",
        "npn",
        "4-20",
        "4 20",
        "4 a 20",
        "0-10v",
        "0 10v",
        "0 a 10v",
        "analogica",
        "analogico",
        "analógica",
        "analógico",
        "digital",
        "rele",
        "relé",
    ]

    if any(term in msg for term in output_terms):
        context["salida"] = original

    # --------------------------------------------------------
    # Conexión explícita
    # --------------------------------------------------------
    connection_terms = [
        "npt",
        "bsp",
        "brida",
        "roscado",
        "rosca",
        "clamp",
        "tri clamp",
        "din",
        "m12",
        "m8",
    ]

    if any(term in msg for term in connection_terms):
        context["conexion"] = original

    # --------------------------------------------------------
    # Diámetro / fracciones / pulgadas
    # --------------------------------------------------------
    if re.search(r"\b\d+/\d+\b", msg) or '"' in original or "'" in original:
        context["diametro"] = original
        context["medida"] = original

    # --------------------------------------------------------
    # Material explícito
    # --------------------------------------------------------
    material_terms = [
        "acero inoxidable",
        "inoxidable",
        "aluminio",
        "bronce",
        "laton",
        "latón",
        "plastico",
        "plástico",
        "pvc",
        "policarbonato",
        "caucho",
        "neopreno",
    ]

    if any(term in msg for term in material_terms):
        context["material"] = original

    # --------------------------------------------------------
    # Aplicación explícita
    # --------------------------------------------------------
    application_markers = [
        "para ",
        "aplicacion",
        "aplicación",
        "uso",
        "trabajo",
        "proceso",
        "maquina",
        "máquina",
        "tanque",
        "pozo",
        "ducto",
        "ductos",
        "tuberia",
        "tubería",
        "linea",
        "línea",
    ]

    if any(marker in msg for marker in application_markers):
        context["aplicacion"] = original

    # --------------------------------------------------------
    # Variables técnicas explícitas
    # --------------------------------------------------------
    if "presion" in msg or "presión" in msg:
        context["presion"] = original

    if "temperatura" in msg:
        context["temperatura"] = original

    if "nivel" in msg:
        context["nivel"] = original

    if "caudal" in msg or "flujo" in msg:
        context["caudal"] = original

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
    - guarda mensaje;
    - revisa si responde a un slot pendiente;
    - extrae contexto objetivo;
    - limpia contexto si llega un código exacto nuevo;
    - actualiza intención.

    Ya no limpia por cambio de familia porque este módulo no clasifica
    familias manuales.
    """
    append_message(session, role="user", content=user_message)

    if detected_intent:
        set_intent(session, detected_intent)

    current_context = session.get("context", {})

    if not isinstance(current_context, dict):
        current_context = {}

    pending_slot = get_last_assistant_question_field(session)

    slot_detection = detect_slot_response(
        message=user_message,
        pending_slot=pending_slot,
        previous_context=current_context,
    )

    extracted = extract_context_from_message(user_message)

    if slot_detection.get("matched"):
        slot_context = slot_detection.get("context", {})

        if isinstance(slot_context, dict):
            # La respuesta al slot tiene prioridad sobre extracción general.
            extracted = {
                **extracted,
                **slot_context,
            }

        if slot_detection.get("clear_pending_slot"):
            clear_last_assistant_question(session)

    # --------------------------------------------------------
    # Caso prioritario: código exacto.
    # --------------------------------------------------------
    # Si el usuario escribe un código exacto, ese código manda por encima
    # de cualquier contexto técnico anterior.
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

    update_context(session, extracted)

    return session