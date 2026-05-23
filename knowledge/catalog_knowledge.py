# ============================================================
# knowledge/catalog_knowledge.py
# ============================================================
# RESPONSABILIDAD:
# Puente entre el catálogo real de VIA y el cerebro conversacional
# de NIA.
#
# Este módulo NO responde al usuario.
# Este módulo NO hace retrieval directo.
# Este módulo SOLO interpreta conocimiento estructurado del
# catálogo para ayudar al árbol de preguntas y al motor dinámico.
#
# Alineado con el documento maestro:
# - jerarquía completa NIVEL_0 -> NIVEL_4
# - características técnicas estructuradas
# - aplicaciones
# - marca
# - referencia
# - texto_busqueda
# - contexto acumulado
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def _normalize(text: Any) -> str:
    """
    Normaliza texto para comparación ligera.
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", text)


def _as_text(value: Any) -> str:
    """
    Convierte cualquier valor a texto seguro.
    """
    if value is None:
        return ""
    return str(value).strip()


def _join_non_empty(parts: List[Any]) -> str:
    """
    Une partes no vacías en un solo texto.
    """
    cleaned = []
    for part in parts:
        text = _as_text(part)
        if text:
            cleaned.append(text)
    return " ".join(cleaned)


# ============================================================
# PALABRAS CLAVE DE CONOCIMIENTO
# ============================================================
# Estas palabras ayudan a clasificar atributos del catálogo.
# No son reglas rígidas; son señales para el árbol dinámico.
# ============================================================

ATTRIBUTE_HINTS = {
    "rango": [
        "rango", "range", "bar", "psi", "kpa", "mpa", "°c", "c", "f",
    ],
    "salida": [
        "salida", "output", "4-20", "0-10v", "pnp", "npn", "relay",
    ],
    "voltaje": [
        "voltaje", "vca", "vcc", "vac", "vdc", "220v", "110v", "24v", "12v",
    ],
    "potencia": [
        "potencia", "hp", "kw", "w", "kva", "va",
    ],
    "rpm": [
        "rpm", "rev/min", "revoluciones",
    ],
    "conexion": [
        "conexion", "conexión", "rosca", "npt", "g1", "g1/4", "g1/2",
    ],
    "comunicacion": [
        "comunicacion", "comunicación", "ethernet", "modbus", "rs485", "usb",
    ],
    "precision": [
        "precision", "precisión", "exactitud",
    ],
    "resolucion": [
        "resolucion", "resolución",
    ],
    "autonomia": [
        "autonomia", "autonomía",
    ],
    "fase": [
        "monofasico", "monofásico", "trifasico", "trifásico",
    ],
    "medida": [
        "medida", "diametro", "diámetro", "torque", "nm", "mm", "pulg",
    ],
    "tipo_accion": [
        "neumatica", "neumática", "electrica", "eléctrica", "manual",
    ],
    "aplicacion": [
        "aplicacion", "aplicación", "uso", "industria",
    ],
}


# ============================================================
# EXTRACCIÓN DE CARACTERÍSTICAS
# ============================================================

def extract_characteristics_map(characteristics: Any) -> Dict[str, List[str]]:
    """
    Convierte CARACTERISTICAS (array de pares título/valor) en un mapa.

    Entrada esperada:
    [
        {"titulo": "Rango", "valor": "0-10 bar"},
        {"titulo": "Salida", "valor": "4-20 mA"}
    ]

    Salida:
    {
        "rango": ["0-10 bar"],
        "salida": ["4-20 mA"]
    }
    """
    result: Dict[str, List[str]] = {}

    if not isinstance(characteristics, list):
        return result

    for item in characteristics:
        if not isinstance(item, dict):
            continue

        title = _normalize(item.get("titulo") or item.get("title") or "")
        value = _as_text(item.get("valor") or item.get("value") or "").strip()

        if not title or not value:
            continue

        key = None
        for attr_key, hints in ATTRIBUTE_HINTS.items():
            if any(hint in title for hint in hints):
                key = attr_key
                break

        if key is None:
            # Si no sabemos la categoría del atributo, lo guardamos
            # como "otros" para no perder información útil.
            key = "otros"

        result.setdefault(key, [])
        if value not in result[key]:
            result[key].append(value)

    return result


# ============================================================
# INFERENCIA DE CATEGORÍA DEL CATÁLOGO
# ============================================================

def infer_category_from_doc(doc: Dict[str, Any]) -> Optional[str]:
    """
    Intenta inferir una categoría general del documento usando:
    - NIVEL_1 / NIVEL_2 / NIVEL_3 / NIVEL_4
    - descripción
    - texto_busqueda
    - aplicaciones
    """
    text = _normalize(
        _join_non_empty([
            doc.get("NIVEL_0"),
            doc.get("NIVEL_1"),
            doc.get("NIVEL_2"),
            doc.get("NIVEL_3"),
            doc.get("NIVEL_4"),
            doc.get("DESCRIPCION_CORTA_PRE"),
            doc.get("DESCRIPCION_LARGA_PRE"),
            doc.get("APLICACIONES"),
            doc.get("texto_busqueda"),
        ])
    )

    category_aliases = {
        "sensor": [
            "sensor", "transmisor", "sonda", "detector", "encoder",
        ],
        "motor": [
            "motor", "motorreductor", "servomotor",
        ],
        "variador": [
            "variador", "drive", "vfd", "arrancador",
        ],
        "plc": [
            "plc", "hmi", "controlador logico", "controlador lógico",
        ],
        "electrico": [
            "breaker", "contactor", "rele", "relé", "guardamotor", "fuente",
        ],
        "valvula": [
            "valvula", "válvula", "electrovalvula", "electroválvula",
            "cilindro", "neumatica", "neumática",
        ],
        "herramienta": [
            "herramienta", "torquimetro", "torquímetro", "taladro", "esmeril",
        ],
        "medicion": [
            "termometro", "termómetro", "camara termica", "cámara térmica",
            "multimetro", "multímetro",
        ],
        "ups": [
            "ups", "no break", "nobreak", "inversor",
        ],
    }

    for category, aliases in category_aliases.items():
        if any(alias in text for alias in aliases):
            return category

    return None


# ============================================================
# KNOWLEDGE DEL PRODUCTO
# ============================================================

def extract_catalog_knowledge(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrae una vista estructurada del conocimiento del producto.

    Esta función es el puente entre el catálogo y el cerebro.
    """
    characteristics = extract_characteristics_map(doc.get("CARACTERISTICAS", []))
    category = infer_category_from_doc(doc)

    hierarchy = {
        "nivel_0": _as_text(doc.get("NIVEL_0")),
        "nivel_1": _as_text(doc.get("NIVEL_1")),
        "nivel_2": _as_text(doc.get("NIVEL_2")),
        "nivel_3": _as_text(doc.get("NIVEL_3")),
        "nivel_4": _as_text(doc.get("NIVEL_4")),
    }

    search_text = _normalize(
        _join_non_empty([
            doc.get("DESCRIPCION_CORTA_PRE"),
            doc.get("DESCRIPCION_LARGA_PRE"),
            doc.get("MARCA_LET"),
            doc.get("REFERENCIA"),
            doc.get("REF_ALTERNATIVA"),
            doc.get("NIVEL_0"),
            doc.get("NIVEL_1"),
            doc.get("NIVEL_2"),
            doc.get("NIVEL_3"),
            doc.get("NIVEL_4"),
            doc.get("APLICACIONES"),
            doc.get("texto_busqueda"),
        ])
    )

    knowledge = {
        "codigo": _as_text(doc.get("CODIGO")),
        "referencia": _as_text(doc.get("REFERENCIA")),
        "ref_alternativa": _as_text(doc.get("REF_ALTERNATIVA")),
        "marca": _as_text(doc.get("MARCA_LET")),
        "categoria": category,
        "jerarquia": hierarchy,
        "descripcion_corta": _as_text(doc.get("DESCRIPCION_CORTA_PRE")),
        "descripcion_larga": _as_text(doc.get("DESCRIPCION_LARGA_PRE")),
        "aplicaciones": _as_text(doc.get("APLICACIONES")),
        "existencia": _as_text(doc.get("EXISTENCIA")),
        "texto_busqueda": search_text,
        "caracteristicas": characteristics,
        "score_oportunidad": doc.get("score_oportunidad"),
        "tipo_sku": _as_text(doc.get("tipo_sku")),
        "visible_en_linea": doc.get("VISIBLE_EN_LINEA"),
        "raw": doc,
    }

    knowledge["signal_attributes"] = extract_signal_attributes(knowledge)

    return knowledge


# ============================================================
# ATRIBUTOS SEÑALADOS
# ============================================================

def extract_signal_attributes(knowledge: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Devuelve los atributos técnicos que sí están presentes
    y que pueden servir como base para preguntas o filtros.
    """
    signals: Dict[str, List[str]] = {}

    characteristics = knowledge.get("caracteristicas", {})
    if isinstance(characteristics, dict):
        for key, values in characteristics.items():
            if values:
                signals[key] = values[:]

    text = _normalize(
        _join_non_empty([
            knowledge.get("descripcion_corta"),
            knowledge.get("descripcion_larga"),
            knowledge.get("texto_busqueda"),
            knowledge.get("aplicaciones"),
            knowledge.get("marca"),
            knowledge.get("referencia"),
        ])
    )

    for attr_key, hints in ATTRIBUTE_HINTS.items():
        if attr_key in signals:
            continue
        if any(hint in text for hint in hints):
            signals[attr_key] = ["detectado_en_texto"]

    return signals


# ============================================================
# PRIORIDAD DE PREGUNTAS
# ============================================================

def get_priority_fields(knowledge: Dict[str, Any]) -> List[str]:
    """
    Devuelve campos prioritarios para preguntas técnicas.
    """
    category = knowledge.get("categoria")

    category_priority_map = {
        "sensor": ["subtipo", "rango", "salida", "conexion", "marca"],
        "motor": ["potencia", "voltaje", "rpm", "marca"],
        "variador": ["potencia", "voltaje", "marca"],
        "plc": ["entradas", "salidas", "comunicacion", "marca"],
        "electrico": ["voltaje", "corriente", "marca"],
        "valvula": ["tipo_accion", "diametro", "voltaje", "marca"],
        "herramienta": ["aplicacion", "medida", "marca"],
        "medicion": ["rango", "precision", "marca"],
        "ups": ["potencia", "autonomia", "fase", "marca"],
    }

    if category in category_priority_map:
        return category_priority_map[category]

    # Fallback general, siguiendo el documento maestro
    return ["marca", "referencia", "aplicacion"]


# ============================================================
# DETECCIÓN DE DATOS YA PRESENTES
# ============================================================

def has_knowledge_value(knowledge: Dict[str, Any], field: str) -> bool:
    """
    Verifica si ya existe un valor útil para un campo.
    """
    if field in knowledge:
        value = knowledge.get(field)
        if value not in [None, "", [], {}]:
            return True

    signals = knowledge.get("signal_attributes", {})
    if isinstance(signals, dict) and field in signals and signals[field]:
        return True

    return False


# ============================================================
# RESUMEN DEL CONOCIMIENTO
# ============================================================

def summarize_knowledge(knowledge: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resumen compacto del conocimiento del producto.
    """
    return {
        "codigo": knowledge.get("codigo"),
        "marca": knowledge.get("marca"),
        "categoria": knowledge.get("categoria"),
        "jerarquia": knowledge.get("jerarquia"),
        "atributos_detectados": list((knowledge.get("signal_attributes") or {}).keys()),
        "visible_en_linea": knowledge.get("visible_en_linea"),
    }


# ============================================================
# SUGERENCIA DE SIGUIENTE ATRIBUTO
# ============================================================

def get_next_question_field(
    knowledge: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Sugiere qué campo preguntar después según el conocimiento
    disponible y el contexto actual.
    """
    context = context or {}
    priority = get_priority_fields(knowledge)

    for field in priority:
        if context.get(field) in [None, "", [], {}]:
            return field

    return None


# ============================================================
# EXPLICACIÓN PARA DEBUG
# ============================================================

def explain_knowledge(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Devuelve una vista de depuración del conocimiento extraído.
    """
    knowledge = extract_catalog_knowledge(doc)

    return {
        "summary": summarize_knowledge(knowledge),
        "priority_fields": get_priority_fields(knowledge),
        "signals": knowledge.get("signal_attributes", {}),
    }