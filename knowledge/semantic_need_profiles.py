# ============================================================
# knowledge/semantic_need_profiles.py
# ============================================================
# RESPONSABILIDAD:
# Resolver perfiles semánticos de necesidades abiertas y filtrar
# resultados reales del catálogo para evitar falsos positivos.
#
# Esta capa pertenece a conocimiento.
#
# NO hace búsqueda.
# NO llama OpenAI.
# NO responde al cliente.
# NO crea oportunidades.
# NO toca Bitrix.
#
# Flujo esperado:
# OpenAI/fallback interpreta necesidad
# → semantic_need_profiles resuelve perfil semántico
# → se filtran productos reales del catálogo
# → el orquestador decide si recomienda o pregunta.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


SEMANTIC_NEED_PROFILES_VERSION = "semantic_need_profiles_v1"


# ============================================================
# UTILIDADES
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte cualquier valor a texto seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def normalize_text(value: Any) -> str:
    """
    Normaliza texto para comparación semántica:
    - convierte a string;
    - minúsculas;
    - elimina acentos;
    - limpia espacios.
    """
    text = _safe_str(value).lower()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text).strip()


def _clean_list(values: Any) -> List[str]:
    """
    Normaliza una lista de términos.
    """
    if not isinstance(values, list):
        return []

    cleaned: List[str] = []

    for item in values:
        text = _safe_str(item)

        if text:
            cleaned.append(text)

    return cleaned


def _contains_any(text: str, terms: List[str]) -> bool:
    """
    Retorna True si el texto contiene al menos un término.
    """
    normalized_text = normalize_text(text)

    return any(
        normalize_text(term) in normalized_text
        for term in terms
        if term
    )


def _count_matches(text: str, terms: List[str]) -> int:
    """
    Cuenta cuántos términos aparecen en el texto.
    """
    normalized_text = normalize_text(text)

    return sum(
        1
        for term in terms
        if term and normalize_text(term) in normalized_text
    )


# ============================================================
# TEXTO DE PRODUCTO
# ============================================================

def build_product_text(product: Dict[str, Any]) -> str:
    """
    Construye texto amplio del producto usando campos reales del catálogo.

    Se usa para detectar señales positivas.
    """
    if not isinstance(product, dict):
        return ""

    parts = [
        product.get("CODIGO"),
        product.get("REFERENCIA"),
        product.get("REF_ALTERNATIVA"),
        product.get("MARCA_LET"),
        product.get("DESCRIPCION_CORTA_PRE"),
        product.get("DESCRIPCION_LARGA_PRE"),
        product.get("NIVEL_0"),
        product.get("NIVEL_1"),
        product.get("NIVEL_2"),
        product.get("NIVEL_3"),
        product.get("NIVEL_4"),
        product.get("APLICACIONES"),
        product.get("texto_busqueda"),

        product.get("codigo"),
        product.get("referencia"),
        product.get("ref_alternativa"),
        product.get("marca"),
        product.get("nombre"),
        product.get("descripcion"),
        product.get("nivel_0"),
        product.get("nivel_1"),
        product.get("nivel_2"),
        product.get("nivel_3"),
        product.get("nivel_4"),
        product.get("aplicaciones"),
    ]

    characteristics = (
        product.get("CARACTERISTICAS")
        or product.get("caracteristicas")
        or []
    )

    if isinstance(characteristics, list):
        for item in characteristics:
            if isinstance(item, dict):
                parts.append(item.get("titulo"))
                parts.append(item.get("title"))
                parts.append(item.get("valor"))
                parts.append(item.get("value"))
            else:
                parts.append(str(item))

    return normalize_text(
        " ".join(str(part) for part in parts if part not in [None, ""])
    )


def build_product_identity_text(product: Dict[str, Any]) -> str:
    """
    Construye texto de identidad principal del producto.

    Se usa para negativos fuertes. Por ejemplo:
    - si la identidad dice agua, no debe recomendarse para aire;
    - si la identidad dice radar de autos, no debe recomendarse para ductos.
    """
    if not isinstance(product, dict):
        return ""

    parts = [
        product.get("DESCRIPCION_CORTA_PRE"),
        product.get("NIVEL_0"),
        product.get("NIVEL_1"),
        product.get("NIVEL_2"),
        product.get("NIVEL_3"),
        product.get("NIVEL_4"),

        product.get("nombre"),
        product.get("descripcion"),
        product.get("nivel_0"),
        product.get("nivel_1"),
        product.get("nivel_2"),
        product.get("nivel_3"),
        product.get("nivel_4"),
    ]

    return normalize_text(
        " ".join(str(part) for part in parts if part not in [None, ""])
    )


# ============================================================
# REGISTRO DE PERFILES SEMÁNTICOS
# ============================================================
# Este registro es extensible.
# Agregar un perfil nuevo NO debe obligar a tocar el orquestador.
# ============================================================

SEMANTIC_NEED_PROFILES: Dict[str, Dict[str, Any]] = {
    "velocidad_aire": {
        "profile_id": "velocidad_aire",
        "family_hint": "medicion",
        "subtype_hint": "velocidad_aire",
        "activation_terms": [
            "anemometro",
            "anemómetro",
            "velocidad aire",
            "velocidad del aire",
            "flujo aire",
            "flujo de aire",
            "ducto",
            "ductos",
            "ventilacion",
            "ventilación",
        ],
        "positive_terms": [
            "anemometro",
            "anemómetro",
            "velocidad del aire",
            "velocidad aire",
            "flujo de aire",
            "flujo aire",
            "medidor de aire",
            "filtro de aire",
            "manometro de aire",
            "manómetro de aire",
            "ducto",
            "ductos",
            "ventilacion",
            "ventilación",
        ],
        "negative_terms": [
            "agua",
            "acueducto",
            "gasolina",
            "octanaje",
            "autos",
            "auto",
            "vehiculo",
            "vehículo",
            "radar",
            "metales",
            "tesoros",
        ],
        "min_positive_matches": 1,
    },

    "presion": {
        "profile_id": "presion",
        "family_hint": "medicion",
        "subtype_hint": "presion",
        "activation_terms": [
            "presion",
            "presión",
            "bar",
            "psi",
            "manometro",
            "manómetro",
            "transmisor de presion",
            "sensor de presion",
        ],
        "positive_terms": [
            "presion",
            "presión",
            "bar",
            "psi",
            "manometro",
            "manómetro",
            "transmisor de presion",
            "sensor de presion",
        ],
        "negative_terms": [
            "temperatura",
            "caudal",
            "nivel",
            "velocidad de autos",
            "radar",
        ],
        "min_positive_matches": 1,
    },

    "temperatura": {
        "profile_id": "temperatura",
        "family_hint": "medicion",
        "subtype_hint": "temperatura",
        "activation_terms": [
            "temperatura",
            "termometro",
            "termómetro",
            "termocupla",
            "pt100",
            "rtd",
        ],
        "positive_terms": [
            "temperatura",
            "termometro",
            "termómetro",
            "termocupla",
            "pt100",
            "rtd",
            "sensor de temperatura",
            "transmisor de temperatura",
        ],
        "negative_terms": [
            "presion",
            "presión",
            "caudal",
            "nivel",
        ],
        "min_positive_matches": 1,
    },

    "caudal": {
        "profile_id": "caudal",
        "family_hint": "medicion",
        "subtype_hint": "caudal",
        "activation_terms": [
            "caudal",
            "flujo",
            "caudalimetro",
            "caudalímetro",
            "flowmeter",
        ],
        "positive_terms": [
            "caudal",
            "flujo",
            "caudalimetro",
            "caudalímetro",
            "flowmeter",
            "medidor de flujo",
        ],
        "negative_terms": [
            "velocidad de autos",
            "radar",
            "octanaje",
        ],
        "min_positive_matches": 1,
    },

    "torque": {
        "profile_id": "torque",
        "family_hint": "herramienta",
        "subtype_hint": "torquimetro",
        "activation_terms": [
            "torque",
            "torquimetro",
            "torquímetro",
            "dinamometrica",
            "dinamométrica",
            "nm",
            "n.m",
            "pies libras",
            "ft-lb",
        ],
        "positive_terms": [
            "torque",
            "torquimetro",
            "torquímetro",
            "dinamometrica",
            "dinamométrica",
            "nm",
            "n.m",
            "ft-lb",
            "pies libras",
        ],
        "negative_terms": [
            "motor",
            "variador",
            "sensor",
        ],
        "min_positive_matches": 1,
    },
}


# ============================================================
# RESOLUCIÓN DE PERFIL
# ============================================================

def build_interpretation_signal_text(
    interpretation: Optional[Dict[str, Any]],
) -> str:
    """
    Construye texto de señales desde la interpretación OpenAI/fallback.

    Este texto se usa para resolver el perfil semántico.
    """
    if not isinstance(interpretation, dict):
        return ""

    parts = [
        interpretation.get("semantic_profile"),
        interpretation.get("profile_id"),
        interpretation.get("family_hint"),
        interpretation.get("subtype_hint"),
        interpretation.get("normalized_query"),
        interpretation.get("reason"),
    ]

    for key in [
        "technical_signals",
        "commercial_signals",
        "positive_terms",
        "negative_terms",
    ]:
        values = interpretation.get(key)

        if isinstance(values, list):
            parts.extend(values)

    return normalize_text(
        " ".join(str(part) for part in parts if part not in [None, ""])
    )


def resolve_semantic_need_profile(
    interpretation: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Resuelve qué perfil semántico aplica.

    Prioridad:
    1. Perfil explícito devuelto por OpenAI/fallback.
    2. Subtipo explícito.
    3. Términos de activación.
    """
    if not isinstance(interpretation, dict):
        return None

    explicit_candidates = [
        interpretation.get("semantic_profile"),
        interpretation.get("profile_id"),
        interpretation.get("subtype_hint"),
    ]

    for candidate in explicit_candidates:
        candidate_norm = normalize_text(candidate)

        if not candidate_norm:
            continue

        for profile_id, profile in SEMANTIC_NEED_PROFILES.items():
            if candidate_norm == normalize_text(profile_id):
                return profile

            if candidate_norm == normalize_text(profile.get("subtype_hint")):
                return profile

    signal_text = build_interpretation_signal_text(interpretation)

    if not signal_text:
        return None

    for profile in SEMANTIC_NEED_PROFILES.values():
        if _contains_any(signal_text, profile.get("activation_terms", [])):
            return profile

    return None


# ============================================================
# TÉRMINOS EFECTIVOS
# ============================================================

def build_effective_positive_terms(
    profile: Dict[str, Any],
    interpretation: Optional[Dict[str, Any]],
) -> List[str]:
    """
    Combina términos positivos del perfil con términos positivos
    que OpenAI/fallback pueda devolver en el futuro.
    """
    terms = list(profile.get("positive_terms", []) or [])

    if isinstance(interpretation, dict):
        terms.extend(_clean_list(interpretation.get("positive_terms")))

    # Eliminamos duplicados preservando orden.
    seen = set()
    unique_terms: List[str] = []

    for term in terms:
        norm = normalize_text(term)

        if not norm or norm in seen:
            continue

        seen.add(norm)
        unique_terms.append(term)

    return unique_terms


def build_effective_negative_terms(
    profile: Dict[str, Any],
    interpretation: Optional[Dict[str, Any]],
) -> List[str]:
    """
    Combina términos negativos del perfil con términos negativos
    que OpenAI/fallback pueda devolver en el futuro.
    """
    terms = list(profile.get("negative_terms", []) or [])

    if isinstance(interpretation, dict):
        terms.extend(_clean_list(interpretation.get("negative_terms")))

    seen = set()
    unique_terms: List[str] = []

    for term in terms:
        norm = normalize_text(term)

        if not norm or norm in seen:
            continue

        seen.add(norm)
        unique_terms.append(term)

    return unique_terms


# ============================================================
# FILTRADO
# ============================================================

def product_matches_semantic_profile(
    product: Dict[str, Any],
    profile: Dict[str, Any],
    interpretation: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Valida si un producto real del catálogo es compatible con un perfil.

    Criterio:
    - debe tener suficientes señales positivas;
    - no debe tener señales negativas fuertes en la identidad principal.
    """
    if not isinstance(product, dict) or not isinstance(profile, dict):
        return False

    product_text = build_product_text(product)
    identity_text = build_product_identity_text(product)

    if not product_text:
        return False

    positive_terms = build_effective_positive_terms(profile, interpretation)
    negative_terms = build_effective_negative_terms(profile, interpretation)

    min_positive_matches = int(profile.get("min_positive_matches", 1) or 1)

    positive_match_count = _count_matches(product_text, positive_terms)

    has_enough_positive = positive_match_count >= min_positive_matches

    has_negative_identity = _contains_any(identity_text, negative_terms)

    return has_enough_positive and not has_negative_identity


def filter_results_for_interpreted_need(
    results: List[dict],
    interpretation: Optional[Dict[str, Any]],
    max_items: int = 10,
) -> List[dict]:
    """
    Filtra resultados del catálogo usando perfiles semánticos.

    Si no hay perfil:
    - devuelve los resultados originales limitados.

    Si hay perfil:
    - devuelve solo productos compatibles.

    Si el perfil filtra todo:
    - devuelve [] para que el orquestador pregunte o responda seguro.
    """
    if not results:
        return []

    profile = resolve_semantic_need_profile(interpretation)

    if not profile:
        return results[:max_items]

    filtered = [
        item
        for item in results
        if product_matches_semantic_profile(
            product=item,
            profile=profile,
            interpretation=interpretation,
        )
    ]

    return filtered[:max_items]


def get_semantic_profile_debug(
    interpretation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Diagnóstico seguro para pruebas internas.

    No expone prompts ni secretos.
    """
    profile = resolve_semantic_need_profile(interpretation)

    return {
        "version": SEMANTIC_NEED_PROFILES_VERSION,
        "profile_detected": bool(profile),
        "profile_id": profile.get("profile_id") if profile else None,
        "family_hint": profile.get("family_hint") if profile else None,
        "subtype_hint": profile.get("subtype_hint") if profile else None,
    }