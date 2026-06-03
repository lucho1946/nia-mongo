# ============================================================
# services/catalog_line_matcher.py
# ============================================================
# RESPONSABILIDAD:
# Calcular relevancia de un producto contra una consulta usando
# la jerarquía real del catálogo VIA:
#
# - NIVEL_0
# - NIVEL_1
# - NIVEL_2
# - NIVEL_3
# - NIVEL_4
# - DESCRIPCION_CORTA_PRE
# - DESCRIPCION_LARGA_PRE
# - REFERENCIA / REF_ALTERNATIVA / CODIGO
# - MARCA_LET
#
# Este módulo reemplaza la lógica manual de "familias industriales".
#
# Reglas:
# - No inventa familias.
# - No clasifica productos con diccionarios artificiales.
# - Prioriza líneas reales del catálogo.
# - Prioriza descripción corta sobre descripción larga.
# - La descripción larga ayuda, pero no debe dominar.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List

from rapidfuzz import fuzz


# ============================================================
# PESOS
# ============================================================
# Mayor peso para campos más estructurados y cercanos a identidad.
# La descripción larga queda con peso menor porque puede contener
# aplicaciones, accesorios o menciones secundarias.
# ============================================================

FIELD_WEIGHTS: Dict[str, float] = {
    "CODIGO": 38.0,
    "REFERENCIA": 34.0,
    "REF_ALTERNATIVA": 30.0,

    # Jerarquía real del catálogo.
    # NIVEL_4 es más específico que NIVEL_0.
    "NIVEL_4": 32.0,
    "NIVEL_3": 28.0,
    "NIVEL_2": 24.0,
    "NIVEL_1": 18.0,
    "NIVEL_0": 12.0,

    # Identidad textual.
    "DESCRIPCION_CORTA_PRE": 26.0,
    "DESCRIPCION_LARGA_PRE": 10.0,

    # Apoyo comercial/técnico.
    "MARCA_LET": 14.0,
    "APLICACIONES": 8.0,
    "texto_busqueda": 8.0,
}


IDENTITY_FIELDS = [
    "CODIGO",
    "REFERENCIA",
    "REF_ALTERNATIVA",
    "NIVEL_0",
    "NIVEL_1",
    "NIVEL_2",
    "NIVEL_3",
    "NIVEL_4",
    "DESCRIPCION_CORTA_PRE",
    "MARCA_LET",
]


CATALOG_LEVEL_FIELDS = [
    "NIVEL_0",
    "NIVEL_1",
    "NIVEL_2",
    "NIVEL_3",
    "NIVEL_4",
]


DESCRIPTION_FIELDS = [
    "DESCRIPCION_CORTA_PRE",
    "DESCRIPCION_LARGA_PRE",
]


REFERENCE_FIELDS = [
    "CODIGO",
    "REFERENCIA",
    "REF_ALTERNATIVA",
]


# Palabras que indican que un producto puede ser accesorio/repuesto.
# Esto NO es familia. Es control de intención principal vs accesorio.
SECONDARY_PRODUCT_TERMS = [
    "accesorio",
    "accesorios",
    "repuesto",
    "repuestos",
    "refaccion",
    "refacciones",
    "display",
    "teclado",
    "panel",
    "tarjeta",
    "modulo",
    "módulo",
    "cable",
    "conector",
    "kit",
    "bobina",
    "adaptador",
    "interfaz",
    "interface",
]


# Si el usuario usa estos términos, sí está pidiendo algo secundario.
SECONDARY_QUERY_TERMS = [
    "accesorio",
    "accesorios",
    "repuesto",
    "repuestos",
    "refaccion",
    "refacciones",
    "display",
    "teclado",
    "panel",
    "tarjeta",
    "modulo",
    "módulo",
    "cable",
    "conector",
    "kit",
    "bobina",
    "adaptador",
    "interfaz",
    "interface",
]


# ============================================================
# NORMALIZACIÓN
# ============================================================

def normalize_text(value: Any) -> str:
    """
    Normaliza texto para comparación:
    - convierte a string;
    - minúsculas;
    - elimina acentos;
    - limpia espacios.
    """
    text = "" if value is None else str(value)
    text = text.lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text).strip()


def extract_tokens(value: Any) -> List[str]:
    """
    Extrae tokens útiles de una consulta.
    """
    text = normalize_text(value)

    tokens = re.findall(r"[a-z0-9][a-z0-9\-/\.]*", text)

    clean_tokens: List[str] = []

    for token in tokens:
        token = token.strip()

        if len(token) < 2:
            continue

        if token not in clean_tokens:
            clean_tokens.append(token)

    return clean_tokens


def _safe_field(product: Dict[str, Any], field: str) -> str:
    """
    Obtiene un campo normalizado del producto.
    """
    if not isinstance(product, dict):
        return ""

    return normalize_text(product.get(field, ""))


def build_catalog_line_text(product: Dict[str, Any]) -> str:
    """
    Construye texto solo con NIVEL_0 a NIVEL_4.
    """
    parts = [
        product.get(field, "")
        for field in CATALOG_LEVEL_FIELDS
    ]

    return normalize_text(" ".join(str(part) for part in parts if part))


def build_identity_text(product: Dict[str, Any]) -> str:
    """
    Construye la identidad principal del producto.

    Importante:
    No usa DESCRIPCION_LARGA_PRE para evitar que menciones secundarias
    dominen la identidad real del producto.
    """
    parts = [
        product.get(field, "")
        for field in IDENTITY_FIELDS
    ]

    return normalize_text(" ".join(str(part) for part in parts if part))


def build_description_text(product: Dict[str, Any]) -> str:
    """
    Construye texto descriptivo del producto.
    """
    parts = [
        product.get(field, "")
        for field in DESCRIPTION_FIELDS
    ]

    return normalize_text(" ".join(str(part) for part in parts if part))


# ============================================================
# MATCHING
# ============================================================

def _field_match_score(query: str, field_value: str, weight: float) -> float:
    """
    Calcula score ponderado entre query y un campo.

    Combina:
    - token_set_ratio para coincidencia por conjunto de términos;
    - partial_ratio para frases parciales;
    - bonus si la query completa aparece dentro del campo.
    """
    query_n = normalize_text(query)
    field_n = normalize_text(field_value)

    if not query_n or not field_n:
        return 0.0

    token_set = fuzz.token_set_ratio(query_n, field_n)
    partial = fuzz.partial_ratio(query_n, field_n)

    base_ratio = (token_set * 0.65) + (partial * 0.35)

    score = (base_ratio / 100.0) * weight

    if query_n in field_n:
        score += weight * 0.35

    return score


def _token_presence_bonus(tokens: List[str], text: str, max_bonus: float) -> float:
    """
    Suma bonus por tokens presentes en un texto.
    """
    text_n = normalize_text(text)

    if not tokens or not text_n:
        return 0.0

    matches = sum(1 for token in tokens if normalize_text(token) in text_n)

    if matches <= 0:
        return 0.0

    ratio = matches / max(len(tokens), 1)

    return min(max_bonus, ratio * max_bonus)


def _query_requests_secondary_product(query: str) -> bool:
    """
    Detecta si el usuario está pidiendo explícitamente accesorio/repuesto.
    """
    query_n = f" {normalize_text(query)} "

    return any(
        f" {normalize_text(term)} " in query_n
        for term in SECONDARY_QUERY_TERMS
    )


def _product_looks_secondary(product: Dict[str, Any]) -> bool:
    """
    Detecta si la identidad del producto parece accesorio/repuesto.
    """
    identity = f" {build_identity_text(product)} "

    return any(
        f" {normalize_text(term)} " in identity
        for term in SECONDARY_PRODUCT_TERMS
    )


def _secondary_product_penalty(query: str, product: Dict[str, Any]) -> float:
    """
    Penaliza accesorios/repuestos cuando el usuario no los pidió.

    Esto reemplaza parte de la antigua lógica por familias, pero sin
    clasificar productos en familias artificiales.
    """
    if _query_requests_secondary_product(query):
        return 0.0

    if _product_looks_secondary(product):
        return -18.0

    return 0.0


def evaluate_catalog_line_match(query: str, product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evalúa relevancia usando líneas reales del catálogo.

    Retorna un debug completo para search.py.
    """
    query_n = normalize_text(query)
    tokens = extract_tokens(query_n)

    if not query_n or not isinstance(product, dict):
        return {
            "score": 0.0,
            "line_score": 0.0,
            "description_short_score": 0.0,
            "description_long_score": 0.0,
            "reference_score": 0.0,
            "brand_score": 0.0,
            "text_search_score": 0.0,
            "token_bonus": 0.0,
            "secondary_penalty": 0.0,
            "matched_levels": [],
            "matched_fields": [],
            "identity_text": "",
            "catalog_line_text": "",
        }

    matched_fields: List[str] = []
    matched_levels: List[str] = []

    field_scores: Dict[str, float] = {}

    for field, weight in FIELD_WEIGHTS.items():
        field_value = _safe_field(product, field)

        score = _field_match_score(query_n, field_value, weight)

        field_scores[field] = score

        # Marcamos match visible si el score es relevante para ese campo.
        if score >= max(weight * 0.35, 4.0):
            matched_fields.append(field)

            if field in CATALOG_LEVEL_FIELDS:
                matched_levels.append(field)

    line_score = sum(field_scores.get(field, 0.0) for field in CATALOG_LEVEL_FIELDS)

    description_short_score = field_scores.get("DESCRIPCION_CORTA_PRE", 0.0)
    description_long_score = field_scores.get("DESCRIPCION_LARGA_PRE", 0.0)

    reference_score = sum(field_scores.get(field, 0.0) for field in REFERENCE_FIELDS)

    brand_score = field_scores.get("MARCA_LET", 0.0)
    text_search_score = field_scores.get("texto_busqueda", 0.0)

    catalog_line_text = build_catalog_line_text(product)
    identity_text = build_identity_text(product)
    description_text = build_description_text(product)

    token_bonus = 0.0
    token_bonus += _token_presence_bonus(tokens, catalog_line_text, max_bonus=18.0)
    token_bonus += _token_presence_bonus(tokens, identity_text, max_bonus=14.0)
    token_bonus += _token_presence_bonus(tokens, description_text, max_bonus=8.0)

    secondary_penalty = _secondary_product_penalty(query_n, product)

    # Score final del matcher.
    # Se limita para que search.py lo combine con score textual y score_nia.
    raw_score = (
        reference_score
        + line_score
        + description_short_score
        + (description_long_score * 0.70)
        + brand_score
        + (text_search_score * 0.60)
        + token_bonus
        + secondary_penalty
    )

    score = max(raw_score, 0.0)

    return {
        "score": round(score, 2),
        "line_score": round(line_score, 2),
        "description_short_score": round(description_short_score, 2),
        "description_long_score": round(description_long_score, 2),
        "reference_score": round(reference_score, 2),
        "brand_score": round(brand_score, 2),
        "text_search_score": round(text_search_score, 2),
        "token_bonus": round(token_bonus, 2),
        "secondary_penalty": round(secondary_penalty, 2),
        "matched_levels": sorted(set(matched_levels)),
        "matched_fields": sorted(set(matched_fields)),
        "identity_text": identity_text,
        "catalog_line_text": catalog_line_text,
    }


def score_catalog_line_match(query: str, product: Dict[str, Any]) -> float:
    """
    Helper simple para tests o uso externo.
    """
    return evaluate_catalog_line_match(query, product).get("score", 0.0)