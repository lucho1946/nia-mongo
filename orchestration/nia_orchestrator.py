# ============================================================
# orchestration/nia_orchestrator.py
# ============================================================
# Cerebro principal de NIA.
#
# Coordina:
# - intención
# - memoria conversacional
# - carga de contexto operativo NIA OS desde JSON
# - política documental
# - búsqueda preliminar en catálogo
# - validación de compatibilidad producto/intención
# - conocimiento del catálogo
# - motor dinámico de preguntas
# - retrieval
# - response engine
#
# Enfoque alineado:
# - NIA no pregunta por preguntar.
# - NIA intenta buscar con el contexto útil disponible.
# - NIA solo recomienda si los resultados coinciden con la necesidad.
# - Si los resultados contradicen la intención, pregunta o pide precisión.
# - Máximo 3 preguntas técnicas antes de recomendar/buscar.
# - Catálogo real como fuente de verdad.
# - Los JSON de NIA OS entran como contexto operativo.
# - La política documental decide cuándo una consulta podría usar documentos,
#   pero todavía NO activa retrieval documental automáticamente.
#
# IMPORTANTE:
# En esta versión:
# - NIA OS se conecta como metadata segura.
# - document_policy se conecta como metadata segura.
# - Todavía NO se inyecta contexto documental al prompt final.
# - Todavía NO se reemplaza catálogo por documentos.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Any, Optional, List

from core.intent_router import detect_intent
from core.response_engine import generate_response

from retrieval.search_adapter import (
    search_products,
    search_exact_code,
)

from memory.conversation_memory import (
    create_session,
    get_session,
    save_session,
    process_memory_update,
    save_last_results,
    append_assistant_message,
    increment_technical_questions,
    reset_technical_questions,
    reset_technical_context,
    get_technical_questions_asked,
    extract_exact_product_code,
    
    # Contexto activo/Ultima preguna
    set_last_assistant_question,
    clear_last_assistant_question,
)

from knowledge.catalog_knowledge import (
    extract_catalog_knowledge,
    get_priority_fields,
)

from knowledge.dynamic_question_engine import (
    decide_next_step,
)

from knowledge.nia_os_loader import (
    build_nia_os_context,
)

from knowledge.document_policy import (
    evaluate_document_policy,
)

from orchestration.commercial_continuity import (
    build_commercial_continuity_response,
    build_commercial_data_capture_response,
    build_commercial_quote_followup_response,
)


# ============================================================
# SESIONES
# ============================================================

def _ensure_session() -> str:
    """
    Crea una sesión nueva cuando el request no trae session_id.

    Decisión técnica:
    - Si un canal quiere mantener continuidad, debe enviar el session_id
      devuelto por NIA en la respuesta anterior.
    - Si no envía session_id, se interpreta como conversación nueva.
    - Esto evita contaminación de contexto entre usuarios o pruebas.
    """
    session = create_session()
    return session["session_id"]


# ============================================================
# UTILIDADES BÁSICAS
# ============================================================

def _normalize(text: Any) -> str:
    """
    Normaliza texto:
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


def _is_clean_greeting(message: str) -> bool:
    """
    Detecta saludo puro sin intención comercial.
    """
    text = _normalize(message)

    if not text:
        return False

    greeting_phrases = {
        "hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hey",
        "que tal",
        "hola buenas",
    }

    if text in greeting_phrases:
        return True

    tokens = set(re.findall(r"[a-zñ]+", text))

    greeting_tokens = {
        "hola",
        "buenas",
        "buenos",
        "dias",
        "tardes",
        "noches",
        "hey",
        "que",
        "tal",
    }

    return bool(tokens) and tokens.issubset(greeting_tokens)


def _extract_exact_code_from_message(message: str) -> Optional[str]:
    """
    Extrae un código exacto de producto aunque venga dentro de una frase.

    Ejemplos:
    - P382280
    - busco el P382280
    - necesito el producto P382280
    - me cotizas P382280

    Esto evita que la memoria anterior contamine búsquedas por código.
    """
    return extract_exact_product_code(message)


def _looks_like_exact_code(message: str) -> bool:
    """
    Compatibilidad con lógica anterior.
    """
    return _extract_exact_code_from_message(message) is not None


def _has_product_context(context: Dict[str, Any]) -> bool:
    """
    Determina si ya existe información útil de producto en memoria.
    """
    keys = [
        "familia",
        "categoria",
        "marca",
        "subtipo",
        "rango",
        "voltaje",
        "potencia",
        "medida",
        "referencia",
        "codigo_producto",
        "aplicacion",
        "entradas",
        "salidas",
        "comunicacion",
        "salida",
        "tipo_accion",
        "diametro",
        "presion",
        "corriente",
        "rpm",
    ]

    return any(
        context.get(key) not in [None, "", [], {}]
        for key in keys
    )


def _count_context_signals(context: Dict[str, Any]) -> int:
    """
    Cuenta señales útiles del contexto para decidir si ya se puede buscar.
    """
    keys = [
        "familia",
        "categoria",
        "marca",
        "subtipo",
        "rango",
        "voltaje",
        "potencia",
        "rpm",
        "medida",
        "aplicacion",
        "entradas",
        "salidas",
        "comunicacion",
        "salida",
        "tipo_accion",
        "diametro",
        "presion",
        "corriente",
    ]

    return sum(
        1 for key in keys
        if context.get(key) not in [None, "", [], {}]
    )


def _build_payload_from_results(intent: str, results: List[dict]) -> Dict[str, Any]:
    """
    Estructura uniforme para response_engine.
    """
    if intent == "codigo_producto":
        if results:
            return {
                "result": results[0] if len(results) == 1 else results
            }

        return {
            "result": []
        }

    return {
        "results": results
    }


def _safe_evaluate_document_policy(
    message: str,
    detected_intent: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evalúa document_policy sin permitir que un error rompa el orquestador.

    Esta función deja la política documental lista como metadata observable.
    Todavía NO ejecuta retrieval documental.
    """
    try:
        return evaluate_document_policy(
            message=message,
            intent=detected_intent,
            context=context,
        )
    except Exception as error:
        return {
            "use_document_context": False,
            "prioritize_catalog": True,
            "source_type": None,
            "confidence": 0.0,
            "reason": f"document_policy_error: {error}",
            "signals": {},
        }


def _attach_nia_os_metadata(
    response: Dict[str, Any],
    nia_os_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Adjunta metadata interna de NIA OS y document_policy a la respuesta.

    Nota:
    - En producción esta metadata puede ocultarse desde el router si se desea.
    - No debe usarse para exponer configuración sensible al cliente.
    """
    response["nia_os"] = {
        "intent": nia_os_context.get("nia_os_intent"),
        "module_ids": nia_os_context.get("module_ids", []),
    }

    document_policy = nia_os_context.get("document_policy")

    if isinstance(document_policy, dict):
        response["document_policy"] = {
            "use_document_context": document_policy.get("use_document_context", False),
            "prioritize_catalog": document_policy.get("prioritize_catalog", True),
            "source_type": document_policy.get("source_type"),
            "confidence": document_policy.get("confidence", 0.0),
            "reason": document_policy.get("reason", ""),
            "is_internal_nia_query": document_policy.get("is_internal_nia_query", False),
            "allow_public_disclosure": document_policy.get("allow_public_disclosure", True),
        }

    return response


# ============================================================
# TEXTO DE PRODUCTO
# ============================================================

def _product_field_text(doc: Dict[str, Any], keys: List[str]) -> str:
    """
    Construye texto normalizado usando solo ciertos campos del producto.
    """
    if not isinstance(doc, dict):
        return ""

    values = []

    for key in keys:
        value = doc.get(key)

        if value not in [None, ""]:
            values.append(str(value))

    return _normalize(" ".join(values))


def _product_text(doc: Dict[str, Any]) -> str:
    """
    Construye texto amplio normalizado del producto para validar
    compatibilidad con la intención del usuario.
    """
    if not isinstance(doc, dict):
        return ""

    parts = [
        doc.get("CODIGO"),
        doc.get("REFERENCIA"),
        doc.get("REF_ALTERNATIVA"),
        doc.get("MARCA_LET"),
        doc.get("DESCRIPCION_CORTA_PRE"),
        doc.get("DESCRIPCION_LARGA_PRE"),
        doc.get("NIVEL_0"),
        doc.get("NIVEL_1"),
        doc.get("NIVEL_2"),
        doc.get("NIVEL_3"),
        doc.get("NIVEL_4"),
        doc.get("APLICACIONES"),
        doc.get("texto_busqueda"),

        doc.get("codigo"),
        doc.get("referencia"),
        doc.get("marca"),
        doc.get("nombre"),
        doc.get("categoria"),
        doc.get("descripcion"),
        doc.get("nivel_1"),
        doc.get("nivel_2"),
        doc.get("nivel_3"),
        doc.get("nivel_4"),
    ]

    characteristics = doc.get("CARACTERISTICAS") or doc.get("caracteristicas")

    if isinstance(characteristics, list):
        for item in characteristics:
            if isinstance(item, dict):
                parts.append(item.get("titulo"))
                parts.append(item.get("title"))
                parts.append(item.get("valor"))
                parts.append(item.get("value"))
            else:
                parts.append(str(item))

    return _normalize(
        " ".join(str(part) for part in parts if part not in [None, ""])
    )


def _product_identity_text(doc: Dict[str, Any]) -> str:
    """
    Texto más estricto del producto:
    nombre, descripción corta y clasificación.

    NO incluye:
    - descripción larga
    - aplicaciones
    - características
    - texto_busqueda

    Esto evita falsos positivos, especialmente en variadores.
    """
    return _product_field_text(
        doc,
        [
            "DESCRIPCION_CORTA_PRE",
            "NIVEL_0",
            "NIVEL_1",
            "NIVEL_2",
            "NIVEL_3",
            "NIVEL_4",
            "nombre",
            "categoria",
            "nivel_1",
            "nivel_2",
            "nivel_3",
            "nivel_4",
        ],
    )


# ============================================================
# COMPATIBILIDAD RESULTADO VS INTENCIÓN
# ============================================================

FAMILY_COMPATIBILITY_TERMS: Dict[str, List[str]] = {
    "sensor": [
        "sensor",
        "transmisor",
        "sonda",
        "detector",
        "presion",
        "temperatura",
        "nivel",
        "caudal",
        "proximidad",
        "inductivo",
        "capacitivo",
        "fotoelectrico",
        "encoder",
    ],
    "motor": [
        "motor",
        "motor electrico",
        "servomotor",
    ],
    "motorreductor": [
        "motorreductor",
        "motor reductor",
        "reductor",
        "motor",
    ],
    "variador": [
        "variador",
        "variadores",
        "variador de frecuencia",
        "convertidor de frecuencia",
        "inversor de frecuencia",
        "vfd",
    ],
    "plc": [
        "plc",
        "controlador logico",
        "controlador programable",
        "hmi",
        "modulo",
        "entrada",
        "salida",
        "io",
        "i/o",
    ],
    "valvula": [
        "valvula",
        "electrovalvula",
        "solenoide",
        "cilindro",
        "neumatica",
        "neumatico",
        "filtro regulador",
    ],
    "herramienta": [
        "herramienta",
        "torquimetro",
        "torque",
        "llave",
        "taladro",
        "esmeril",
        "destornillador",
        "dinamometrica",
    ],
    "medicion": [
        "termometro",
        "camara termica",
        "multimetro",
        "analizador",
        "medidor",
        "medicion",
    ],
    "ups": [
        "ups",
        "nobreak",
        "no break",
        "inversor",
        "bateria",
    ],
    "electrico": [
        "breaker",
        "contactor",
        "rele",
        "guardamotor",
        "fuente",
        "switching",
        "interruptor",
        "disyuntor",
    ],
}


SUBTYPE_COMPATIBILITY_TERMS: Dict[str, List[str]] = {
    "presion": [
        "presion",
        "bar",
        "psi",
        "transmisor de presion",
        "sensor de presion",
    ],
    "temperatura": [
        "temperatura",
        "termometro",
        "termocupla",
        "pt100",
        "rtd",
    ],
    "nivel": [
        "nivel",
    ],
    "caudal": [
        "caudal",
        "flujo",
    ],
        "fotoelectrico": [
        "fotoelectrico",
        "foto electrico",
        "fotocelda",
        "foto celda",
        "photoelectric",
        "photo electric",
        "sensor fotoelectrico",
        "sensor foto electrico",
        "reflectivo",
        "retroreflectivo",
        "barrera",
        "difuso",
    ],
    "inductivo": [
        "inductivo",
        "sensor inductivo",
        "proximidad inductiva",
        "proximidad inductivo",
    ],
    "capacitivo": [
        "capacitivo",
        "sensor capacitivo",
        "proximidad capacitiva",
        "proximidad capacitivo",
    ],
    "reflectivo": [
        "reflectivo",
        "retroreflectivo",
        "retro reflectivo",
        "reflex",
        "reflector",
        "fotoelectrico",
    ],
    "barrera": [
        "barrera",
        "tipo barrera",
        "emisor receptor",
        "emisor y receptor",
        "fotoelectrico",
    ],
    "difuso": [
        "difuso",
        "difusa",
        "deteccion difusa",
        "detección difusa",
        "fotoelectrico",
    ],
    "torquimetro": [
        "torquimetro",
        "torque",
        "dinamometrica",
        "dinamometrico",
        "nm",
        "n.m",
        "n-m",
    ],
}


def _detect_requested_subtype_from_context(context: Dict[str, Any]) -> Optional[str]:
    """
    Detecta subtipo fuerte desde el contexto.
    """
    subtype = context.get("subtipo")

    if subtype:
        return _normalize(subtype)

    family = context.get("familia")

    if family == "herramienta" and context.get("medida"):
        medida = _normalize(context.get("medida"))

        if "nm" in medida or "n.m" in medida or "n-m" in medida:
            return "torquimetro"

    return None


def _product_matches_terms(product_text: str, terms: List[str]) -> bool:
    """
    Valida si el texto del producto contiene alguno de los términos.
    """
    if not product_text:
        return False

    return any(
        _normalize(term) in product_text
        for term in terms
    )


def _is_variador_compatible(doc: Dict[str, Any]) -> bool:
    """
    Regla ultra estricta para variadores.

    Para evitar falsos positivos como:
    - Cutter carnico Industrial
    - maquinaria con HP
    - equipos industriales con motor

    Solo se acepta como variador si la identidad principal del producto
    contiene explícitamente términos de variador.
    """
    identity_text = _product_identity_text(doc)

    strong_terms = [
        "variador",
        "variadores",
        "variador de frecuencia",
        "convertidor de frecuencia",
        "inversor de frecuencia",
        "vfd",
    ]

    negative_terms = [
        "cutter",
        "carnico",
        "cárnico",
        "mezclador",
        "molino",
        "horno",
        "maquina",
        "máquina",
        "bomba",
        "motor electrico",
        "motor eléctrico",
    ]

    if any(_normalize(term) in identity_text for term in negative_terms):
        return False

    return any(_normalize(term) in identity_text for term in strong_terms)


def _parse_number(value: str) -> Optional[float]:
    """
    Convierte un número textual a float.
    Soporta coma decimal.
    """
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _extract_requested_torque_nm(context: Dict[str, Any]) -> Optional[float]:
    """
    Extrae el torque solicitado por el usuario en Nm.

    Ejemplos válidos:
    - 200nm
    - 200 nm
    - 200 n.m
    - 150 ft-lb
    - 150 pies-libras

    Retorna siempre el valor convertido a Nm.
    """
    raw_values = [
        context.get("medida"),
        context.get("rango"),
        context.get("potencia"),
    ]

    text = _normalize(
        " ".join(str(value) for value in raw_values if value not in [None, ""])
    )

    if not text:
        return None

    nm_match = re.search(
        r"(\d+(?:[\.,]\d+)?)\s*(nm|n\.m|n-m|newton\s*metro|newton\s*metros)\b",
        text,
    )

    if nm_match:
        return _parse_number(nm_match.group(1))

    ftlb_match = re.search(
        r"(\d+(?:[\.,]\d+)?)\s*(ft[\s-]*lb|lb[\s-]*ft|pies[\s-]*libras|pie[\s-]*libra|libras[\s-]*pie)\b",
        text,
    )

    if ftlb_match:
        value = _parse_number(ftlb_match.group(1))

        if value is not None:
            return value * 1.35582

    return None


def _extract_product_torque_values_nm(doc: Dict[str, Any]) -> List[float]:
    """
    Extrae valores de torque encontrados en el producto y los convierte a Nm.

    Esta validación evita errores peligrosos como recomendar:
    - usuario pide 200 Nm
    - producto dice 2000 pies-libras
    """
    text = _product_text(doc)

    if not text:
        return []

    values: List[float] = []

    nm_patterns = [
        r"(\d+(?:[\.,]\d+)?)\s*(nm|n\.m|n-m|newton\s*metro|newton\s*metros)\b",
    ]

    ftlb_patterns = [
        r"(\d+(?:[\.,]\d+)?)\s*(ft[\s-]*lb|lb[\s-]*ft|pies[\s-]*libras|pie[\s-]*libra|libras[\s-]*pie)\b",
    ]

    for pattern in nm_patterns:
        for match in re.finditer(pattern, text):
            value = _parse_number(match.group(1))

            if value is not None:
                values.append(value)

    for pattern in ftlb_patterns:
        for match in re.finditer(pattern, text):
            value = _parse_number(match.group(1))

            if value is not None:
                values.append(value * 1.35582)

    return values


def _is_torque_value_compatible(
    requested_nm: Optional[float],
    product_values_nm: List[float],
) -> bool:
    """
    Valida compatibilidad de torque.

    Política:
    - Si el usuario no dio torque numérico, no bloquea.
    - Si el usuario sí dio torque numérico, el producto debe tener
      un valor explícito cercano.
    - Tolerancia comercial: ±25%, para permitir equivalentes cercanos.
    """
    if requested_nm is None:
        return True

    if not product_values_nm:
        return False

    min_allowed = requested_nm * 0.75
    max_allowed = requested_nm * 1.25

    return any(
        min_allowed <= value <= max_allowed
        for value in product_values_nm
    )


def _is_torquimetro_compatible(
    doc: Dict[str, Any],
    context: Dict[str, Any],
) -> bool:
    """
    Regla estricta para torquímetros.

    Primero valida que el producto sea realmente un torquímetro.
    Después valida unidad/capacidad cuando el usuario pidió una medida.
    """
    product_text = _product_text(doc)

    if not _product_matches_terms(
        product_text,
        SUBTYPE_COMPATIBILITY_TERMS["torquimetro"],
    ):
        return False

    requested_nm = _extract_requested_torque_nm(context)
    product_values_nm = _extract_product_torque_values_nm(doc)

    return _is_torque_value_compatible(
        requested_nm=requested_nm,
        product_values_nm=product_values_nm,
    )


def _is_plc_compatible(
    doc: Dict[str, Any],
    context: Dict[str, Any],
) -> bool:
    """
    Regla más estricta para PLC.

    Evita que una búsqueda contextual como:
    - plc + 16 entradas + modbus

    termine recomendando un accesorio genérico tipo:
    - Entrada modbus rtu

    La intención principal sigue siendo PLC, por eso debe aparecer
    PLC/controlador lógico en la identidad principal del producto.
    """
    identity_text = _product_identity_text(doc)
    product_text = _product_text(doc)

    strong_plc_terms = [
        "plc",
        "controlador logico",
        "controladores logicos",
        "controlador programable",
        "controladores programables",
        "control logico programable",
    ]

    accessory_terms = [
        "entrada modbus",
        "salida modbus",
        "modulo de entrada",
        "modulo entrada",
        "modulo de salida",
        "modulo salida",
        "gateway",
        "convertidor",
    ]

    has_strong_identity = any(
        _normalize(term) in identity_text
        for term in strong_plc_terms
    )

    if has_strong_identity:
        return True

    if any(_normalize(term) in product_text for term in accessory_terms):
        return False

    return False


def _is_product_compatible_with_context(
    doc: Dict[str, Any],
    context: Dict[str, Any],
) -> bool:
    """
    Valida si un producto es compatible con el contexto principal.
    """
    product_text = _product_text(doc)

    if not product_text:
        return False

    family = (
        context.get("familia")
        or context.get("categoria")
        or ""
    )

    family = _normalize(family)

    if not family:
        return True

    if family == "variador":
        return _is_variador_compatible(doc)

    if family == "plc":
        return _is_plc_compatible(doc, context)

    requested_subtype = _detect_requested_subtype_from_context(context)

    if requested_subtype == "torquimetro":
        return _is_torquimetro_compatible(doc, context)

    family_terms = FAMILY_COMPATIBILITY_TERMS.get(family)

    if family_terms and not _product_matches_terms(
        product_text,
        family_terms,
    ):
        return False

    if requested_subtype:
        subtype_terms = SUBTYPE_COMPATIBILITY_TERMS.get(requested_subtype)

        if subtype_terms and not _product_matches_terms(
            product_text,
            subtype_terms,
        ):
            return False

    return True


def _filter_compatible_results(
    results: List[dict],
    context: Dict[str, Any],
    max_items: int = 10,
) -> List[dict]:
    """
    Filtra resultados que contradicen la intención principal.
    """
    if not results:
        return []

    family = context.get("familia") or context.get("categoria")

    if not family:
        return results[:max_items]

    compatible = [
        item for item in results
        if _is_product_compatible_with_context(item, context)
    ]

    return compatible[:max_items]


def _results_are_good_enough(results: List[dict], context: Dict[str, Any]) -> bool:
    """
    Determina si los resultados son buenos para recomendar.
    """
    if not results:
        return False

    family = context.get("familia") or context.get("categoria")

    if family:
        return _is_product_compatible_with_context(results[0], context)

    return True


# ============================================================
# PRIORIDADES CONVERSACIONALES
# ============================================================

def _get_priority_fields_from_context(context: Dict[str, Any]) -> List[str]:
    """
    Devuelve campos prioritarios según familia/categoría.
    """
    family = (
        context.get("familia")
        or context.get("categoria")
        or ""
    )

    family = _normalize(family)

    priority_map = {
        "sensor": [
            "subtipo",
            "rango",
            "salida",
            "conexion",
            "marca",
        ],
        "motor": [
            "potencia",
            "voltaje",
            "marca",
            "rpm",
        ],
        "motorreductor": [
            "potencia",
            "voltaje",
            "marca",
            "rpm",
            "medida",
        ],
        "variador": [
            "potencia",
            "voltaje",
            "marca",
        ],
        "plc": [
            "entradas",
            "salidas",
            "comunicacion",
            "marca",
        ],
        "valvula": [
            "tipo_accion",
            "diametro",
            "voltaje",
            "presion",
            "marca",
        ],
        "herramienta": [
            "medida",
            "marca",
            "aplicacion",
        ],
        "medicion": [
            "rango",
            "precision",
            "marca",
        ],
        "ups": [
            "potencia",
            "autonomia",
            "voltaje",
            "fase",
            "marca",
        ],
        "electrico": [
            "voltaje",
            "corriente",
            "marca",
        ],
    }

    return priority_map.get(
        family,
        ["referencia", "marca", "aplicacion"],
    )


# ============================================================
# KNOWLEDGE DEL CATÁLOGO
# ============================================================

def _build_catalog_knowledge_from_results(
    results: List[dict],
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Extrae knowledge desde el primer resultado compatible.
    """
    if not results:
        return None

    context = context or {}

    compatible_results = _filter_compatible_results(
        results=results,
        context=context,
        max_items=1,
    )

    if not compatible_results:
        return None

    top_product = compatible_results[0]

    if not isinstance(top_product, dict):
        return None

    knowledge = extract_catalog_knowledge(top_product)
    knowledge["priority_fields"] = get_priority_fields(knowledge)

    context_family = (
        context.get("familia")
        or context.get("categoria")
    )

    knowledge_category = knowledge.get("categoria")

    if context_family and knowledge_category:
        if _normalize(context_family) != _normalize(knowledge_category):
            return None

    return knowledge


def _get_dynamic_priority_fields(
    context: Dict[str, Any],
    catalog_knowledge: Optional[Dict[str, Any]],
) -> List[str]:
    """
    Decide el orden de preguntas.
    La familia expresada por el usuario manda primero.
    """
    context_family = (
        context.get("familia")
        or context.get("categoria")
    )

    if context_family:
        return _get_priority_fields_from_context(context)

    if catalog_knowledge:
        priority = catalog_knowledge.get("priority_fields")

        if isinstance(priority, list) and priority:
            return priority

    return [
        "referencia",
        "marca",
        "aplicacion",
    ]


# ============================================================
# BÚSQUEDA SEGURA
# ============================================================

def _safe_search_products(query: str) -> List[dict]:
    """
    Ejecuta búsqueda de productos de forma segura.

    Objetivo:
    - Evitar que NIA se caiga si MongoDB Atlas falla temporalmente.
    - Devolver lista vacía cuando hay error de conexión.
    - Permitir que el orquestador responda con fallback controlado.
    """
    try:
        return search_products(query)
    except Exception as error:
        print(f"[NIA][WARN] Error en búsqueda de productos: {error}")
        return []


# ============================================================
# CONSULTA ENRIQUECIDA
# ============================================================

def _build_search_query(message: str, context: Dict[str, Any]) -> str:
    """
    Construye una consulta enriquecida con contexto acumulado.
    No inventa datos. Solo agrega datos presentes en memoria.
    """
    parts = [message]

    if context.get("subtipo") == "torquimetro":
        parts.append("torquimetro")

    for key in [
        "familia",
        "categoria",
        "marca",
        "subtipo",
        "rango",
        "voltaje",
        "potencia",
        "salida",
        "conexion",
        "medida",
        "comunicacion",
        "aplicacion",
        "tipo_accion",
        "diametro",
        "presion",
        "entradas",
        "salidas",
        "rpm",
        "corriente",
    ]:
        value = context.get(key)

        if value in [None, "", [], {}]:
            continue

        value_txt = str(value).strip()

        if not value_txt:
            continue

        if value_txt.lower() not in message.lower():
            parts.append(value_txt)

    return " ".join(parts).strip()


# ============================================================
# POLÍTICA DE DECISIÓN
# ============================================================

def _should_recommend_now(
    message: str,
    context: Dict[str, Any],
    preliminary_results: List[dict],
    questions_asked: int,
) -> bool:
    """
    Decide si ya debemos recomendar.
    """
    if not preliminary_results:
        return False

    if not _results_are_good_enough(preliminary_results, context):
        return False

    if questions_asked >= 3:
        return True

    family = context.get("familia") or context.get("categoria")
    signals = _count_context_signals(context)

    if (
        family in ["motor", "motorreductor", "variador"]
        and context.get("potencia")
        and context.get("voltaje")
    ):
        return True

    if (
        family == "herramienta"
        and context.get("subtipo") == "torquimetro"
        and context.get("medida")
    ):
        return True

    if (
        family == "plc"
        and (
            context.get("comunicacion")
            or context.get("entradas")
            or context.get("salidas")
        )
        and signals >= 2
    ):
        return True

    if family == "sensor" and context.get("subtipo") and context.get("rango"):
        return True

    if family and context.get("marca") and signals >= 2:
        return True

    if family and signals >= 3:
        return True

    text = _normalize(message)

    if any(
        token in text
        for token in ["bar", "psi", "hp", "kw", "220v", "110v", "24v", "modbus", "ethernet", "nm"]
    ):
        if family and signals >= 2:
            return True

    return False


def _make_no_compatible_results_response(
    detected_intent: str,
    context: Dict[str, Any],
    session_id: str,
) -> Dict[str, Any]:
    """
    Respuesta segura cuando hay resultados preliminares,
    pero ninguno coincide con la intención/familia del usuario.
    """
    family = (
        context.get("subtipo")
        or context.get("familia")
        or context.get("categoria")
        or "producto"
    )

    potencia = context.get("potencia")
    voltaje = context.get("voltaje")
    marca = context.get("marca")
    referencia = context.get("referencia")
    medida = context.get("medida")

    if context.get("familia") == "motor" and potencia and voltaje:
        detalle_motor = []

        if marca:
            detalle_motor.append(str(marca))

        detalle_motor.append(str(potencia))
        detalle_motor.append(str(voltaje))

        detalle_txt = ", ".join(detalle_motor)

        return {
            "intent": detected_intent,
            "response": (
                f"No encontré motores compatibles con {detalle_txt} "
                "en los resultados actuales. ¿Tienes la referencia exacta "
                "o quieres que revise equivalentes cercanos?"
            ),
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": "no_compatible_motor_with_power_voltage",
        }

    if context.get("familia") == "motor" and potencia and not voltaje:
        detalle_motor = []

        if marca:
            detalle_motor.append(str(marca))

        detalle_motor.append(str(potencia))
        detalle_txt = ", ".join(detalle_motor)

        return {
            "intent": detected_intent,
            "response": (
                f"No encontré motores suficientemente compatibles con {detalle_txt} "
                "usando los datos actuales. ¿Qué voltaje necesita? "
                "Ej: 220V, 230/460V o 440V."
            ),
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": "no_compatible_motor_missing_voltage",
        }

    if context.get("familia") == "variador" and potencia and voltaje:
        return {
            "intent": detected_intent,
            "response": (
                f"No encontré variadores compatibles con {potencia} y {voltaje} "
                "en los resultados actuales. ¿Tienes una marca o referencia "
                "para afinar la búsqueda? También puedo revisar equivalentes."
            ),
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": "no_compatible_variador_with_power_voltage",
        }

    if context.get("familia") == "variador" and potencia and not voltaje:
        return {
            "intent": detected_intent,
            "response": (
                f"No encontré variadores suficientemente compatibles con {potencia} "
                "usando los datos actuales. ¿Qué voltaje necesita? "
                "Ej: 220V o 440V."
            ),
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": "no_compatible_variador_missing_voltage",
        }

    if (
        context.get("familia") == "herramienta"
        and context.get("subtipo") == "torquimetro"
        and medida
    ):
        return {
            "intent": detected_intent,
            "response": (
                f"No encontré torquímetros compatibles con {medida} "
                "en los resultados actuales. ¿Tienes una referencia específica "
                "o quieres que revise equivalentes cercanos?"
            ),
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": "no_compatible_torquimetro_with_measure",
        }

    detalle = []

    if potencia:
        detalle.append(str(potencia))

    if voltaje:
        detalle.append(str(voltaje))

    if marca:
        detalle.append(str(marca))

    if referencia:
        detalle.append(str(referencia))

    if medida:
        detalle.append(str(medida))

    detalle_txt = ""

    if detalle:
        detalle_txt = " con " + ", ".join(detalle)

    return {
        "intent": detected_intent,
        "response": (
            f"No encontré resultados suficientemente compatibles con {family}{detalle_txt} "
            "en los resultados actuales. ¿Me puedes confirmar una referencia, "
            "marca o especificación clave para afinar la búsqueda?"
        ),
        "needs_clarification": True,
        "context": context,
        "session_id": session_id,
        "decision_reason": "no_compatible_results",
    }

def _extract_channel_phone_from_cliente_id(cliente_id: Optional[str]) -> Optional[str]:
    """
    Extrae teléfono desde cliente_id cuando representa un contacto real.

    Casos válidos:
    - 3001234567
    - 573001234567
    - +573001234567
    - whatsapp:+573001234567

    Casos NO válidos:
    - anonimo
    - test_azure_x
    - cliente_web_demo
    """
    raw = "" if cliente_id is None else str(cliente_id).strip()

    if not raw:
        return None

    normalized_text = raw.lower()

    blocked_keywords = [
        "anonimo",
        "anonymous",
        "test",
        "demo",
        "azure",
        "web",
        "cliente",
        "user",
        "session",
    ]

    if any(keyword in normalized_text for keyword in blocked_keywords):
        return None

    digits = re.sub(r"\D", "", raw)

    if digits.startswith("57") and len(digits) >= 12:
        digits = digits[2:]

    if 7 <= len(digits) <= 10:
        return digits

    return None


def _apply_channel_contact_fallback(
    session: Dict[str, Any],
    canal: Optional[str],
    cliente_id: Optional[str],
) -> Dict[str, Any]:
    """
    Guarda en sesión el teléfono del canal cuando cliente_id parece número.

    Esta regla implementa la premisa comercial:
    si el cliente no entrega datos, la cotización se puede asociar
    al número desde el cual escribió.
    """
    if not isinstance(session, dict):
        return session

    canal = "" if canal is None else str(canal).strip().lower()
    cliente_id = "" if cliente_id is None else str(cliente_id).strip()

    if canal:
        session["canal"] = canal

    if cliente_id:
        session["cliente_id"] = cliente_id

    channel_phone = _extract_channel_phone_from_cliente_id(cliente_id)

    if not channel_phone:
        return session

    session["channel_contact_phone"] = channel_phone
    session["commercial_contact_source"] = "channel_phone"

    commercial_data = session.setdefault("commercial_data", {})

    if not commercial_data.get("telefono"):
        commercial_data["telefono"] = channel_phone
        session["commercial_data"] = commercial_data

    return session


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

def process_message(
    message: str,
    session_id: Optional[str] = None,
    canal: Optional[str] = None,
    cliente_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Procesa un mensaje del usuario y devuelve la respuesta final de NIA.
    """

    # --------------------------------------------------------
    # 1. Recuperar / crear sesión
    # --------------------------------------------------------
    if not session_id:
        session_id = _ensure_session()

    session = get_session(session_id)

    if not session:
        session = create_session()
        session_id = session["session_id"]
        
    # --------------------------------------------------------
    # 1.1. Contacto de respaldo por canal
    # --------------------------------------------------------
    # Si el request trae cliente_id como número telefónico
    # —por ejemplo desde WhatsApp—, lo usamos como teléfono
    # comercial de respaldo para no bloquear cotización.
    # --------------------------------------------------------
    session = _apply_channel_contact_fallback(
        session=session,
        canal=canal,
        cliente_id=cliente_id,
    )

    # --------------------------------------------------------
    # 2. Detectar intención
    # --------------------------------------------------------
    intent_data = detect_intent(message)
    detected_intent = intent_data.get("intent", "general")

    # --------------------------------------------------------
    # 2.1. Cargar contexto operativo NIA OS
    # --------------------------------------------------------
    nia_os_context = build_nia_os_context(detected_intent)

    # --------------------------------------------------------
    # 3. Actualizar memoria
    # --------------------------------------------------------
    session = process_memory_update(
        session=session,
        user_message=message,
        detected_intent=detected_intent,
    )

    context = session.get("context", {})

    # --------------------------------------------------------
    # 3.1. Evaluar política documental
    # --------------------------------------------------------
    # Esta evaluación todavía NO activa retrieval documental.
    # Solo deja metadata segura para trazabilidad y futura integración.
    document_policy = _safe_evaluate_document_policy(
        message=message,
        detected_intent=detected_intent,
        context=context,
    )

    nia_os_context["document_policy"] = document_policy
    
    # --------------------------------------------------------
    # 3.2. Guardrail público para consultas internas de NIA
    # --------------------------------------------------------
    # Si un cliente pregunta por reglas, módulos, prompts, arquitectura
    # o configuración interna, NIA NO debe buscar productos ni exponer
    # detalles sensibles. Responde de forma pública y segura.
    #----------------------------------------------------------
    
    if (
        document_policy.get("is_internal_nia_query") is True
        and document_policy.get("public_safe_response")
    ):
        safe_public_response = {
            "intent": detected_intent,
            "response": document_policy.get("public_safe_response"),
            "needs_clarification": False,
            "context": context,
            "session_id": session_id,
            "decision_reason": "public_safe_internal_nia_query",
            "compatible_count": 0,
        }

        append_assistant_message(
            session,
            safe_public_response.get("response", ""),
        )
        save_session(session)

        return _attach_nia_os_metadata(
            safe_public_response,
            nia_os_context,
        )
    
    # --------------------------------------------------------
    # 3.2.1 Captura de datos comerciales estructurados
    # --------------------------------------------------------
    # Si NIA ya inició una cotización y el cliente responde con:
    # - nombre
    # - empresa
    # - correo
    # - teléfono
    # - cantidad
    # - presupuesto
    # - fecha estimada
    #
    # NIA debe guardar esos datos y pedir solo lo faltante.
    # Esto ejecuta la instrucción del Motor Comercial:
    # "Solicitar únicamente los datos faltantes".
    # --------------------------------------------------------
    commercial_data_response = build_commercial_data_capture_response(
        session=session,
        message=message,
        detected_intent=detected_intent,
    )

    if commercial_data_response:
        clear_last_assistant_question(session)

        append_assistant_message(
            session,
            commercial_data_response.get("response", ""),
        )

        save_session(session)

        return _attach_nia_os_metadata(
            commercial_data_response,
            nia_os_context,
        )
    
    # --------------------------------------------------------
    # 3.2.2 Seguimiento de cotización enviada / recibida
    # --------------------------------------------------------
    # NIA debe continuar en seguimiento, no iniciar una nueva cotización.
    # --------------------------------------------------------
    commercial_quote_followup_response = build_commercial_quote_followup_response(
        session=session,
        message=message,
        detected_intent=detected_intent,
    )

    if commercial_quote_followup_response:
        clear_last_assistant_question(session)

        append_assistant_message(
            session,
            commercial_quote_followup_response.get("response", ""),
        )

        save_session(session)

        return _attach_nia_os_metadata(
            commercial_quote_followup_response,
            nia_os_context,
        )    
        
    # --------------------------------------------------------
    # 3.3. Continuidad comercial con último producto seleccionado
    # --------------------------------------------------------
    # Si el usuario ya seleccionó un producto y luego dice:
    # - "Envíame una cotización"
    # - "Quiero cotizar"
    # - "Lo quiero"
    # - "Me interesa"
    #
    # NIA debe continuar con ese producto.
    # NO debe ejecutar search_products("Enviame una cotizacion").
    # --------------------------------------------------------
    commercial_continuity_response = build_commercial_continuity_response(
        session=session,
        message=message,
        detected_intent=detected_intent,
    )

    if commercial_continuity_response:
        clear_last_assistant_question(session)

        # Esta respuesta ya no es una pregunta técnica pendiente.
        # Evitamos que una pregunta anterior contamine el flujo comercial.
        clear_last_assistant_question(session)

        append_assistant_message(
            session,
            commercial_continuity_response.get("response", ""),
        )
        save_session(session)

        return _attach_nia_os_metadata(
            commercial_continuity_response,
            nia_os_context,
        )

    # --------------------------------------------------------
    # 4. Saludo puro
    # --------------------------------------------------------
    if _is_clean_greeting(message):
        final_response = generate_response(intent_data=intent_data)

        append_assistant_message(session, final_response.get("response", ""))
        save_session(session)

        final_response["session_id"] = session_id
        final_response["context"] = context

        return _attach_nia_os_metadata(final_response, nia_os_context)

        # --------------------------------------------------------
    # 5. Código exacto dentro de cualquier frase
    # --------------------------------------------------------
    # Regla fuerte:
    # Si el usuario menciona un código exacto, el código manda.
    # Se ignora/limpia contexto anterior para evitar contaminación
    # de memoria, por ejemplo:
    # - antes: "precio variador 3hp 220v"
    # - después: "busco el P382280"
    # Debe buscar P382280, no seguir en variador.
    # --------------------------------------------------------
    exact_code = (
        _extract_exact_code_from_message(message)
        or intent_data.get("code")
    )

    if exact_code:
        exact_code = str(exact_code).strip()

        reset_technical_context(session, preserve_history=True)

        session.setdefault("context", {})
        session["context"]["codigo_producto"] = exact_code
        session["context"]["referencia"] = exact_code

        code_results = search_exact_code(exact_code)

        payload = _build_payload_from_results("codigo_producto", code_results)

        final_response = generate_response(
            intent_data={
                **intent_data,
                "intent": "codigo_producto",
                "code": exact_code,
            },
            search_payload=payload,
        )

        if code_results:
            # Guarda el resultado como último producto seleccionado.
            # Esto es clave para que luego frases como:
            # "quiero cotizar este producto"
            # "enviame la cotizacion"
            # puedan usar el producto activo.
            save_last_results(session, code_results)
            reset_technical_questions(session)
            clear_last_assistant_question(session)

        append_assistant_message(session, final_response.get("response", ""))

        # IMPORTANTE:
        # Antes faltaba persistir la sesión en esta rama.
        # Sin esto, NIA respondía el producto exacto, pero no guardaba
        # last_selected_product para el siguiente mensaje.
        save_session(session)

        final_response["session_id"] = session_id
        final_response["context"] = session.get("context", {})
        final_response["decision_reason"] = "exact_code_detected_inside_message"
        final_response["exact_code"] = exact_code

        return _attach_nia_os_metadata(final_response, nia_os_context)
    
    
    # --------------------------------------------------------
    # 6. Comercial genérico sin producto
    # --------------------------------------------------------
    if detected_intent == "comercial" and not _has_product_context(context):
        final_response = generate_response(intent_data=intent_data)

        append_assistant_message(session, final_response.get("response", ""))
        save_session(session)

        final_response["session_id"] = session_id
        final_response["context"] = context

        return _attach_nia_os_metadata(final_response, nia_os_context)

    # --------------------------------------------------------
    # 7. Búsqueda preliminar con contexto acumulado
    # --------------------------------------------------------
    search_query = _build_search_query(
        message=message,
        context=context,
    )

    preliminary_results = _safe_search_products(search_query)

    compatible_results = _filter_compatible_results(
        results=preliminary_results,
        context=context,
        max_items=10,
    )

    catalog_knowledge = _build_catalog_knowledge_from_results(
        preliminary_results,
        context=context,
    )

    technical_questions_asked = get_technical_questions_asked(session)
    
    # --------------------------------------------------------
    # 7.1. Regla fuerte para torquímetros
    # --------------------------------------------------------
    # Si el usuario pide un torquímetro pero aún no dio capacidad,
    # NIA debe preguntar la medida antes de recomendar.
    #
    # Esto evita recomendar productos incompatibles como:
    # - usuario pide torquímetro
    # - NIA recomienda 2000 pies-libras sin saber si necesita 200 Nm
    # --------------------------------------------------------
    if (
        context.get("familia") == "herramienta"
        and context.get("subtipo") == "torquimetro"
        and not context.get("medida")
        and technical_questions_asked < 3
    ):
        response = "¿Qué medida, tamaño o capacidad necesitas? Por ejemplo: 200 Nm, 100 Nm o 50 Nm."

        # Guardamos el slot pendiente para que si el usuario responde:
        # "200nm", NIA entienda que está respondiendo la medida.
        set_last_assistant_question(
            session=session,
            field="medida",
            question=response,
        )

        increment_technical_questions(session)
        append_assistant_message(session, response)
        save_session(session)

        result = {
            "intent": detected_intent,
            "response": response,
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": "torquimetro_missing_measure",
            "compatible_count": 0,
        }

        return _attach_nia_os_metadata(result, nia_os_context)
    
    

    # --------------------------------------------------------
    # 8. Si hay resultados compatibles + contexto útil, recomendar.
    # --------------------------------------------------------
    if _should_recommend_now(
        message=message,
        context=context,
        preliminary_results=compatible_results,
        questions_asked=technical_questions_asked,
    ):
        save_last_results(session, compatible_results)
        reset_technical_questions(session)
        clear_last_assistant_question(session)

        payload = _build_payload_from_results(detected_intent, compatible_results)

        response_intent_data = intent_data

        if detected_intent == "comercial" and compatible_results:
            response_intent_data = {
                **intent_data,
                "intent": "producto",
            }

        final_response = generate_response(
            intent_data=response_intent_data,
            search_payload=payload,
        )

        append_assistant_message(session, final_response.get("response", ""))
        save_session(session)

        final_response["session_id"] = session_id
        final_response["context"] = context
        final_response["decision_reason"] = "recommend_with_compatible_context"
        final_response["compatible_count"] = len(compatible_results)

        return _attach_nia_os_metadata(final_response, nia_os_context)

    # --------------------------------------------------------
    # 9. Si hay resultados pero ninguno es compatible.
    # --------------------------------------------------------
    if preliminary_results and not compatible_results and _has_product_context(context):

        if (
            context.get("familia") == "motor"
            and context.get("potencia")
            and context.get("voltaje")
        ):
            safe_response = _make_no_compatible_results_response(
                detected_intent=detected_intent,
                context=context,
                session_id=session_id,
            )

            append_assistant_message(session, safe_response.get("response", ""))
            save_session(session)

            return _attach_nia_os_metadata(safe_response, nia_os_context)

        if (
            context.get("familia") == "herramienta"
            and context.get("subtipo") == "torquimetro"
            and context.get("medida")
        ):
            safe_response = _make_no_compatible_results_response(
                detected_intent=detected_intent,
                context=context,
                session_id=session_id,
            )

            append_assistant_message(session, safe_response.get("response", ""))
            save_session(session)

            return _attach_nia_os_metadata(safe_response, nia_os_context)

        if (
            context.get("familia") == "variador"
            and context.get("potencia")
            and context.get("voltaje")
        ):
            safe_response = _make_no_compatible_results_response(
                detected_intent=detected_intent,
                context=context,
                session_id=session_id,
            )

            append_assistant_message(session, safe_response.get("response", ""))
            save_session(session)

            return _attach_nia_os_metadata(safe_response, nia_os_context)

        priority_fields = _get_dynamic_priority_fields(
            context=context,
            catalog_knowledge=None,
        )

        decision = decide_next_step(
            context=context,
            questions_asked=technical_questions_asked,
            priority_fields=priority_fields,
        )

        if decision.get("action") == "ask" and technical_questions_asked < 3:
            question_data = decision.get("question", {}) or {}

            response = question_data.get(
                "question",
                "¿Me puedes confirmar una referencia, marca o especificación clave?",
            )

            # Guardamos qué campo estaba preguntando NIA.
            # Ejemplo: field="subtipo" para "¿Qué tipo específico necesitas?"
            set_last_assistant_question(
                session=session,
                field=question_data.get("field"),
                question=response,
            )

            increment_technical_questions(session)
            append_assistant_message(session, response)
            save_session(session)

            result = {
                "intent": detected_intent,
                "response": response,
                "needs_clarification": True,
                "context": context,
                "session_id": session_id,
                "decision_reason": "results_not_compatible_ask_more",
                "priority_fields": priority_fields,
                "compatible_count": 0,
            }

            return _attach_nia_os_metadata(result, nia_os_context)

        safe_response = _make_no_compatible_results_response(
            detected_intent=detected_intent,
            context=context,
            session_id=session_id,
        )

        append_assistant_message(session, safe_response.get("response", ""))
        save_session(session)

        return _attach_nia_os_metadata(safe_response, nia_os_context)

    # --------------------------------------------------------
    # 10. Si no hay suficiente certeza, preguntar una cosa útil.
    # --------------------------------------------------------
    priority_fields = _get_dynamic_priority_fields(
        context=context,
        catalog_knowledge=catalog_knowledge,
    )

    decision = decide_next_step(
        context=context,
        questions_asked=technical_questions_asked,
        priority_fields=priority_fields,
    )

    # Caso especial:
    # Si el motor dinámico decide buscar, pero Mongo no devolvió resultados
    # preliminares para un motor con potencia + voltaje, no usamos fallback
    # genérico. Damos respuesta técnica segura.
    if (
        decision.get("action") == "search"
        and not preliminary_results
        and context.get("familia") == "motor"
        and context.get("potencia")
        and context.get("voltaje")
    ):
        safe_response = _make_no_compatible_results_response(
            detected_intent=detected_intent,
            context=context,
            session_id=session_id,
        )

        append_assistant_message(session, safe_response.get("response", ""))
        save_session(session)

        return _attach_nia_os_metadata(safe_response, nia_os_context)

    if decision.get("action") == "ask":
        question_data = decision.get("question", {}) or {}

        response = question_data.get(
            "question",
            "¿Me puedes dar más información del producto que necesitas?",
        )

        # Guardamos el slot pendiente para interpretar la próxima respuesta.
        set_last_assistant_question(
            session=session,
            field=question_data.get("field"),
            question=response,
        )

        increment_technical_questions(session)
        append_assistant_message(session, response)
        save_session(session)

        result = {
            "intent": detected_intent,
            "response": response,
            "needs_clarification": True,
            "context": context,
            "session_id": session_id,
            "decision_reason": decision.get("reason"),
            "priority_fields": priority_fields,
            "compatible_count": len(compatible_results),
        }

        return _attach_nia_os_metadata(result, nia_os_context)

    # --------------------------------------------------------
    # 11. Fallback: recomendar solo compatibles.
    # --------------------------------------------------------
    search_results = compatible_results

    if not search_results and preliminary_results and _has_product_context(context):
        safe_response = _make_no_compatible_results_response(
            detected_intent=detected_intent,
            context=context,
            session_id=session_id,
        )

        append_assistant_message(session, safe_response.get("response", ""))
        save_session(session)

        return _attach_nia_os_metadata(safe_response, nia_os_context)

    if (
        not search_results
        and not preliminary_results
        and context.get("familia") == "motor"
        and context.get("potencia")
        and context.get("voltaje")
    ):
        safe_response = _make_no_compatible_results_response(
            detected_intent=detected_intent,
            context=context,
            session_id=session_id,
        )

        append_assistant_message(session, safe_response.get("response", ""))
        save_session(session)

        return _attach_nia_os_metadata(safe_response, nia_os_context)

    save_last_results(session, search_results)
    reset_technical_questions(session)
    clear_last_assistant_question(session)

    payload = _build_payload_from_results(detected_intent, search_results)

    response_intent_data = intent_data

    if detected_intent == "comercial" and search_results:
        response_intent_data = {
            **intent_data,
            "intent": "producto",
        }

    final_response = generate_response(
        intent_data=response_intent_data,
        search_payload=payload,
    )

    append_assistant_message(session, final_response.get("response", ""))
    save_session(session)

    final_response["session_id"] = session_id
    final_response["context"] = context
    final_response["decision_reason"] = decision.get("reason")
    final_response["priority_fields"] = priority_fields
    final_response["compatible_count"] = len(search_results)

    return _attach_nia_os_metadata(final_response, nia_os_context)