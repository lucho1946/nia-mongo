# ============================================================
# orchestration/commercial_proforma.py
# ============================================================
# RESPONSABILIDAD:
# Gestionar la transición desde cotización/seguimiento hacia
# proforma o cierre comercial.
#
# Este módulo NO busca productos.
# Este módulo NO reemplaza el catálogo.
# Este módulo solo trabaja cuando ya existe contexto comercial:
# - producto activo
# - cotización en proceso/lista
# - seguimiento de cotización
#
# Alineación con Don Andrés:
# - Si el cliente quiere comprar, no volver a vender desde cero.
# - Avanzar a proforma.
# - Pedir RUT, NIT o documento fiscal como dato clave.
# - No repetir datos que ya existen en memoria.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


# ============================================================
# UTILIDADES BÁSICAS
# ============================================================

def _normalize(text: Any) -> str:
    """
    Normaliza texto para detectar frases naturales:
    - convierte a string
    - minúsculas
    - sin acentos
    - espacios limpios
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text)


def _has_value(value: Any) -> bool:
    """
    Indica si un campo tiene un valor útil.
    """
    return value not in [None, "", [], {}]


def _get_commercial_data(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene commercial_data de forma segura.
    """
    data = session.get("commercial_data")

    if isinstance(data, dict):
        return data

    return {}


def _get_active_product(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Obtiene el producto activo desde sesión.
    """
    product = session.get("last_selected_product")

    if isinstance(product, dict) and product.get("codigo"):
        return product

    product_code = session.get("last_selected_product_code")

    if product_code:
        return {
            "codigo": product_code,
        }

    return None


# ============================================================
# DETECCIÓN DE INTENCIÓN DE PROFORMA / COMPRA
# ============================================================

PROFORMA_BUY_INTENT_PHRASES = [
    # Compra directa
    "quiero comprar",
    "lo compro",
    "me interesa comprar",
    "voy a comprar",
    "vamos a comprar",
    "quiero adquirir",
    "lo voy a adquirir",

    # Aprobación de cotización
    "apruebo",
    "aprobado",
    "aprobada",
    "apruebo la cotizacion",
    "apruebo la cotización",
    "ya esta aprobada",
    "ya está aprobada",
    "acepto",
    "acepto la cotizacion",
    "acepto la cotización",
    "me sirve",
    "esta bien",
    "está bien",
    "ok sigamos",
    "listo sigamos",

    # Continuar proceso
    "quiero seguir",
    "sigamos",
    "continuemos",
    "procedamos",
    "avancemos",
    "siguiente paso",
    "demosle",
    "démosle",
    "dale",
    "hagamoslo",
    "hagámoslo",

    # Pago
    "quiero pagar",
    "como pago",
    "cómo pago",
    "donde pago",
    "dónde pago",
    "medio de pago",
    "formas de pago",

    # Proforma explícita
    "proforma",
    "hagamos la proforma",
    "hacer la proforma",
    "envíame la proforma",
    "enviame la proforma",
    "mándame la proforma",
    "mandame la proforma",
    "necesito la proforma",
    "generemos la proforma",
    "generar proforma",
]


def is_proforma_intent_message(message: str) -> bool:
    """
    Detecta si el cliente quiere avanzar a compra/proforma.

    Importante:
    Esta función solo detecta intención.
    La decisión final también exige contexto comercial previo.
    """
    text = _normalize(message)

    if not text:
        return False

    if any(_normalize(phrase) in text for phrase in PROFORMA_BUY_INTENT_PHRASES):
        return True

    # Patrones cortos comunes después de recibir cotización.
    short_acceptance_patterns = {
        "si",
        "sí",
        "ok",
        "listo",
        "correcto",
        "de acuerdo",
        "esta bien",
        "está bien",
    }

    return text in {_normalize(item) for item in short_acceptance_patterns}


def _has_commercial_context_for_proforma(session: Dict[str, Any]) -> bool:
    """
    Valida si hay contexto suficiente para iniciar proforma.

    No necesitamos todos los datos comerciales todavía, pero sí
    debe existir al menos producto activo o estado comercial previo.
    """
    if _get_active_product(session):
        return True

    estado = _normalize(session.get("estado_negociacion"))
    commercial_process_state = _normalize(session.get("commercial_process_state"))

    states_that_allow_proforma = {
        "datos_cotizacion_recibidos",
        "cotizacion_lista_para_asesor",
        "seguimiento_cotizacion",
        "seguimiento",
        "cotizacion_enviada",
        "cotizacion_recibida",
    }

    if estado in states_that_allow_proforma:
        return True

    if commercial_process_state in states_that_allow_proforma:
        return True

    return False

# ============================================================
# EXTRACCIÓN DE DOCUMENTO FISCAL / RUT / NIT
# ============================================================

def _is_waiting_for_proforma_data(session: Dict[str, Any]) -> bool:
    """
    Determina si NIA está esperando datos de proforma.

    Casos válidos:
    - NIA ya pidió RUT/NIT/documento fiscal.
    - El estado interno está en proforma_en_proceso.
    - El Commercial Spine está en pedir_datos_faltantes_proforma.
    """
    estado = _normalize(session.get("estado_negociacion"))
    commercial_process_state = _normalize(session.get("commercial_process_state"))

    if estado in {
        "proforma_en_proceso",
        "datos_proforma_parciales",
    }:
        return True

    if commercial_process_state in {
        "pedir_datos_faltantes_proforma",
        "preparar_proforma",
    }:
        return True

    datos_faltantes = session.get("datos_faltantes_proforma")

    if isinstance(datos_faltantes, list) and datos_faltantes:
        return True

    return False


def extract_fiscal_document(message: str) -> Optional[Dict[str, str]]:
    """
    Extrae RUT, NIT o documento fiscal desde un mensaje natural.

    Ejemplos:
    - "Mi NIT es 900123456-7"
    - "NIT 900.123.456-7"
    - "RUT 901234567"
    - "Documento fiscal 900123456"
    - "900123456-7"

    Retorna:
    {
        "tipo": "nit" | "rut" | "documento_fiscal",
        "valor": "900123456-7"
    }
    """
    raw = "" if message is None else str(message).strip()

    if not raw:
        return None

    normalized = _normalize(raw)

    # --------------------------------------------------------
    # 1. Detectar documento con etiqueta explícita.
    # --------------------------------------------------------
    labeled_patterns = [
        ("nit", r"\b(?:nit|n\.i\.t)\b\s*(?:es|:|-)?\s*([0-9][0-9\.\-\s]{5,20}[0-9])"),
        ("rut", r"\b(?:rut|r\.u\.t)\b\s*(?:es|:|-)?\s*([0-9][0-9\.\-\s]{5,20}[0-9])"),
        (
            "documento_fiscal",
            r"\b(?:documento fiscal|documento tributario|documento|cedula|c[eé]dula|cc)\b\s*(?:es|:|-)?\s*([0-9][0-9\.\-\s]{5,20}[0-9])",
        ),
    ]

    for doc_type, pattern in labeled_patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if match:
            value = match.group(1).strip()
            value = re.sub(r"\s+", "", value)

            digits = re.sub(r"\D", "", value)

            if 6 <= len(digits) <= 15:
                return {
                    "tipo": doc_type,
                    "valor": value,
                }

    # --------------------------------------------------------
    # 2. Si no hay etiqueta, pero NIA acaba de pedir el documento,
    # aceptamos una respuesta corta con número fiscal.
    #
    # Ejemplos:
    # - "900123456-7"
    # - "901234567"
    # --------------------------------------------------------
    generic_match = re.search(
        r"\b([0-9][0-9\.\-\s]{5,20}[0-9])\b",
        raw,
        flags=re.IGNORECASE,
    )

    if generic_match:
        value = generic_match.group(1).strip()
        value = re.sub(r"\s+", "", value)

        digits = re.sub(r"\D", "", value)

        if 6 <= len(digits) <= 15:
            return {
                "tipo": "documento_fiscal",
                "valor": value,
            }

    return None


def _save_fiscal_document(
    session: Dict[str, Any],
    fiscal_document: Dict[str, str],
) -> Dict[str, Any]:
    """
    Guarda el documento fiscal dentro de commercial_data.

    Guardamos siempre:
    - documento_fiscal

    Y adicionalmente:
    - nit, si el usuario dijo NIT.
    - rut, si el usuario dijo RUT.
    """
    commercial_data = session.setdefault("commercial_data", {})

    doc_type = fiscal_document.get("tipo") or "documento_fiscal"
    value = fiscal_document.get("valor")

    if not value:
        return commercial_data

    commercial_data["documento_fiscal"] = value

    if doc_type == "nit":
        commercial_data["nit"] = value

    if doc_type == "rut":
        commercial_data["rut"] = value

    session["commercial_data"] = commercial_data

    return commercial_data

# ============================================================
# DATOS FALTANTES DE PROFORMA
# ============================================================

def calculate_proforma_missing_fields(session: Dict[str, Any]) -> List[str]:
    """
    Calcula datos faltantes para poder preparar proforma.

    Primera integración:
    - producto
    - contacto comercial
    - documento fiscal / RUT / NIT

    Nota:
    Don Andrés recalcó que para proforma es muy importante pedir:
    RUT, NIT o documento fiscal.
    """
    missing: List[str] = []

    commercial_data = _get_commercial_data(session)

    if not _get_active_product(session):
        missing.append("producto")

    has_contact = bool(
        commercial_data.get("correo")
        or commercial_data.get("telefono")
        or session.get("channel_contact_phone")
    )

    if not has_contact:
        missing.append("correo o teléfono")

    fiscal_document = (
        commercial_data.get("documento_fiscal")
        or commercial_data.get("nit")
        or commercial_data.get("rut")
        or commercial_data.get("documento")
    )

    if not fiscal_document:
        missing.append("RUT, NIT o documento fiscal")

    return missing


def _build_missing_question(missing_fields: List[str]) -> str:
    """
    Construye una pregunta única y clara.
    """
    if not missing_fields:
        return ""

    if "RUT, NIT o documento fiscal" in missing_fields:
        return "¿me confirmas RUT, NIT o documento fiscal?"

    if "correo o teléfono" in missing_fields:
        return "¿me confirmas correo o teléfono de contacto?"

    if "producto" in missing_fields:
        return "¿me confirmas sobre qué producto avanzamos?"

    return f"¿me confirmas {missing_fields[0]}?"


# ============================================================
# RESPUESTA PRINCIPAL DE PROFORMA
# ============================================================

def build_commercial_proforma_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Optional[Dict[str, Any]]:
    """
    Construye respuesta de proforma/cierre si el cliente expresa
    intención de comprar, aprobar, pagar o pedir proforma.

    Este bloque debe ejecutarse antes de búsqueda normal para evitar que:
    "quiero comprar" o "hagamos proforma"
    termine como búsqueda de producto.
    """
    if not is_proforma_intent_message(message):
        return None

    if not _has_commercial_context_for_proforma(session):
        return None

    commercial_data = _get_commercial_data(session)

    missing_fields = calculate_proforma_missing_fields(session)

    name = commercial_data.get("nombre_cliente")
    prefix = f"Perfecto, {name}." if name else "Perfecto."

    # --------------------------------------------------------
    # Estado interno de proforma.
    # --------------------------------------------------------
    if missing_fields:
        session["estado_negociacion"] = "proforma_en_proceso"
        session["commercial_process_state"] = "pedir_datos_faltantes_proforma"
        session["ultimo_paso"] = "preparar_proforma"
        session["siguiente_paso"] = "esperar_respuesta_cliente"
        session["datos_faltantes_proforma"] = missing_fields
    else:
        session["estado_negociacion"] = "datos_proforma_recibidos"
        session["commercial_process_state"] = "proforma_lista_para_asesor"
        session["ultimo_paso"] = "proforma_lista_para_asesor"
        session["siguiente_paso"] = "pago_pendiente"
        session["datos_faltantes_proforma"] = []

    # --------------------------------------------------------
    # Respuesta.
    # --------------------------------------------------------
    if missing_fields:
        question = _build_missing_question(missing_fields)

        response = (
            f"{prefix} Para avanzar con la proforma, {question}"
        )
    else:
        response = (
            f"{prefix} Ya tengo los datos necesarios para dejar la proforma "
            "lista para revisión del asesor."
        )

    return {
        "intent": detected_intent,
        "response": response,
        "needs_clarification": bool(missing_fields),
        "context": session.get("context", {}),
        "session_id": session.get("session_id"),
        "decision_reason": "commercial_proforma_flow",
        "compatible_count": 1 if _get_active_product(session) else 0,
        "requires_customer_data": bool(missing_fields),

        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes_proforma": session.get("datos_faltantes_proforma"),

        "cards": [session.get("last_selected_product")]
        if isinstance(session.get("last_selected_product"), dict)
        else [],
        "results": [session.get("last_selected_product")]
        if isinstance(session.get("last_selected_product"), dict)
        else [],
    }
    
def build_commercial_proforma_data_capture_response(
    session: Dict[str, Any],
    message: str,
    detected_intent: str,
) -> Optional[Dict[str, Any]]:
    """
    Captura datos faltantes de proforma cuando NIA ya los pidió.

    Flujo esperado:
    - NIA: "¿me confirmas RUT, NIT o documento fiscal?"
    - Cliente: "NIT 900123456-7"
    - NIA guarda el documento y avanza a proforma_lista_para_asesor.

    Este bloque evita que el NIT/RUT caiga como búsqueda de producto.
    """
    if not _is_waiting_for_proforma_data(session):
        return None

    fiscal_document = extract_fiscal_document(message)

    if not fiscal_document:
        return None

    commercial_data = _save_fiscal_document(
        session=session,
        fiscal_document=fiscal_document,
    )

    missing_fields = calculate_proforma_missing_fields(session)

    name = commercial_data.get("nombre_cliente")
    prefix = f"Gracias, {name}." if name else "Gracias."

    # --------------------------------------------------------
    # Si todavía falta algo, seguimos en proforma_en_proceso.
    # --------------------------------------------------------
    if missing_fields:
        session["estado_negociacion"] = "datos_proforma_parciales"
        session["commercial_process_state"] = "pedir_datos_faltantes_proforma"
        session["ultimo_paso"] = "pedir_datos_faltantes_proforma"
        session["siguiente_paso"] = "esperar_respuesta_cliente"
        session["datos_faltantes_proforma"] = missing_fields

        question = _build_missing_question(missing_fields)

        response = (
            f"{prefix} Ya tengo el documento fiscal. "
            f"Para continuar con la proforma, {question}"
        )

        needs_clarification = True
        requires_customer_data = True

    # --------------------------------------------------------
    # Si no falta nada, la proforma queda lista para asesor.
    # --------------------------------------------------------
    else:
        session["estado_negociacion"] = "datos_proforma_recibidos"
        session["commercial_process_state"] = "proforma_lista_para_asesor"
        session["ultimo_paso"] = "proforma_lista_para_asesor"
        session["siguiente_paso"] = "pago_pendiente"
        session["datos_faltantes_proforma"] = []

        response = (
            f"{prefix} Ya tengo el documento fiscal. "
            "Con estos datos puedo dejar la proforma lista para revisión del asesor."
        )

        needs_clarification = False
        requires_customer_data = False

    active_product = _get_active_product(session)

    cards = [
        session.get("last_selected_product")
    ] if isinstance(session.get("last_selected_product"), dict) else []

    results = [
        session.get("last_selected_product")
    ] if isinstance(session.get("last_selected_product"), dict) else []

    return {
        "intent": detected_intent,
        "response": response,
        "needs_clarification": needs_clarification,
        "context": session.get("context", {}),
        "session_id": session.get("session_id"),
        "decision_reason": "commercial_proforma_data_capture",
        "compatible_count": 1 if active_product else 0,
        "requires_customer_data": requires_customer_data,

        "estado_negociacion": session.get("estado_negociacion"),
        "commercial_process_id": session.get("commercial_process_id"),
        "commercial_process_state": session.get("commercial_process_state"),
        "ultimo_paso": session.get("ultimo_paso"),
        "siguiente_paso": session.get("siguiente_paso"),
        "datos_faltantes_proforma": session.get("datos_faltantes_proforma"),

        "cards": cards,
        "results": results,
    }