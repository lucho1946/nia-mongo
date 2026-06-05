# ============================================================
# knowledge/nia_os/runtime_policy_loader.py
# ============================================================
# RESPONSABILIDAD:
# Cargar reglas runtime desde módulos NIA OS y convertirlas en
# texto seguro para prompts de OpenAI.
#
# Esta capa permite que NIA OS sea la fuente oficial de reglas,
# evitando duplicar políticas dentro del código de orquestación.
#
# Reglas:
# - No ejecuta OpenAI.
# - No busca productos.
# - No consulta MongoDB.
# - No recomienda productos.
# - Solo carga JSON local de NIA OS y construye política runtime.
# ============================================================

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

NIA_OS_MODULES_PATH = PROJECT_ROOT / "knowledge" / "nia_os" / "modules"

SEMANTIC_INTERPRETATION_MODULE_PATH = (
    NIA_OS_MODULES_PATH / "module_motor_interpretacion_semantica.json"
)

RUNTIME_POLICY_LOADER_VERSION = "nia_os_runtime_policy_loader_v1"


# ============================================================
# FALLBACK MÍNIMO SEGURO
# ============================================================
# Este fallback solo se usa si el JSON no existe o falla.
# No reemplaza el módulo NIA OS; solo evita que el runtime quede
# sin guardrails.
# ============================================================

DEFAULT_ALLOWED_RESPONSIBILITIES = [
    "detectar_intencion_del_usuario",
    "extraer_necesidad_en_lenguaje_natural",
    "generar_normalized_query_derivada_del_mensaje",
    "extraer_senales_tecnicas_mencionadas_por_el_usuario",
    "indicar_si_se_debe_buscar_en_catalogo",
    "proponer_maximo_una_pregunta_de_aclaracion",
]

DEFAULT_FORBIDDEN_RESPONSIBILITIES = [
    "recomendar_producto_final",
    "seleccionar_producto_final",
    "inventar_producto",
    "inventar_codigo",
    "inventar_referencia",
    "inventar_marca",
    "inventar_precio",
    "inventar_stock",
    "inventar_disponibilidad",
    "inventar_tiempo_entrega",
    "inventar_nivel_0",
    "inventar_nivel_1",
    "inventar_nivel_2",
    "inventar_nivel_3",
    "inventar_nivel_4",
    "usar_familias_manuales_como_criterio_de_busqueda",
    "usar_marcas_manuales_como_criterio_de_busqueda",
    "usar_taxonomias_manuales_como_criterio_de_busqueda",
]

DEFAULT_CORE_CONCEPTS = [
    "normalized_query",
    "product_need_terms",
    "technical_signals",
    "commercial_signals",
    "catalog_real_as_source_of_truth",
]


# ============================================================
# UTILIDADES
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte cualquier valor a string seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def _clean_string_list(value: Any) -> List[str]:
    """
    Normaliza listas de strings.
    """
    if not isinstance(value, list):
        return []

    result: List[str] = []

    for item in value:
        text = _safe_str(item)
        if text:
            result.append(text)

    return result


def _read_json_file(path: Path) -> Dict[str, Any]:
    """
    Lee un archivo JSON local de forma segura.
    """
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def _extract_first_list(data: Dict[str, Any], keys: List[str]) -> List[str]:
    """
    Busca la primera lista disponible en varias claves posibles.
    Esto hace el loader tolerante a cambios menores de estructura.
    """
    for key in keys:
        value = data.get(key)
        cleaned = _clean_string_list(value)

        if cleaned:
            return cleaned

    return []


def _extract_nested_first_list(
    data: Dict[str, Any],
    parent_keys: List[str],
    child_keys: List[str],
) -> List[str]:
    """
    Busca listas dentro de objetos anidados.
    """
    for parent_key in parent_keys:
        parent = data.get(parent_key)

        if not isinstance(parent, dict):
            continue

        found = _extract_first_list(parent, child_keys)

        if found:
            return found

    return []


def _format_list_as_bullets(items: List[str]) -> str:
    """
    Convierte una lista en bullets para prompt.
    """
    cleaned = _clean_string_list(items)

    if not cleaned:
        return "- No definido."

    return "\n".join(f"- {item}" for item in cleaned)


# ============================================================
# CARGA DE MÓDULO SEMÁNTICO
# ============================================================

@lru_cache(maxsize=1)
def load_semantic_interpretation_module() -> Dict[str, Any]:
    """
    Carga el módulo oficial de interpretación semántica desde NIA OS.

    Si no existe o falla, devuelve {}.
    """
    return _read_json_file(SEMANTIC_INTERPRETATION_MODULE_PATH)


def extract_semantic_runtime_policy() -> Dict[str, Any]:
    """
    Extrae reglas runtime del módulo de interpretación semántica.

    La función es tolerante a estructura:
    - lee claves directas si existen;
    - lee claves anidadas si existen;
    - usa fallback mínimo si faltan campos.
    """
    module = load_semantic_interpretation_module()

    allowed = (
        _extract_first_list(
            module,
            [
                "allowed_responsibilities",
                "allowed_actions",
                "allowed_runtime_responsibilities",
            ],
        )
        or _extract_nested_first_list(
            module,
            ["runtime_policy", "openai_policy", "policy", "rules"],
            [
                "allowed_responsibilities",
                "allowed_actions",
                "allowed_runtime_responsibilities",
            ],
        )
        or DEFAULT_ALLOWED_RESPONSIBILITIES
    )

    forbidden = (
        _extract_first_list(
            module,
            [
                "forbidden_responsibilities",
                "forbidden_actions",
                "forbidden_runtime_responsibilities",
            ],
        )
        or _extract_nested_first_list(
            module,
            ["runtime_policy", "openai_policy", "policy", "rules"],
            [
                "forbidden_responsibilities",
                "forbidden_actions",
                "forbidden_runtime_responsibilities",
            ],
        )
        or DEFAULT_FORBIDDEN_RESPONSIBILITIES
    )

    concepts = (
        _extract_first_list(
            module,
            [
                "new_core_concepts",
                "core_concepts",
                "runtime_core_concepts",
            ],
        )
        or _extract_nested_first_list(
            module,
            ["runtime_policy", "openai_policy", "policy", "rules"],
            [
                "new_core_concepts",
                "core_concepts",
                "runtime_core_concepts",
            ],
        )
        or DEFAULT_CORE_CONCEPTS
    )

    return {
        "ok": bool(module),
        "version": RUNTIME_POLICY_LOADER_VERSION,
        "source": str(SEMANTIC_INTERPRETATION_MODULE_PATH),
        "module_id": module.get("module_id", "module_motor_interpretacion_semantica"),
        "module_version": module.get("version", ""),
        "allowed_responsibilities": allowed,
        "forbidden_responsibilities": forbidden,
        "core_concepts": concepts,
        "used_fallback": not bool(module),
    }


def build_openai_runtime_policy_prompt() -> str:
    """
    Construye el bloque de política runtime que se enviará a OpenAI.

    Importante:
    - No envía el JSON completo.
    - Solo envía reglas compactas y relevantes.
    - El catálogo real sigue siendo fuente de verdad.
    """
    policy = extract_semantic_runtime_policy()

    allowed = policy.get("allowed_responsibilities", [])
    forbidden = policy.get("forbidden_responsibilities", [])
    concepts = policy.get("core_concepts", [])

    return (
        "POLÍTICA RUNTIME NIA OS PARA INTERPRETACIÓN SEMÁNTICA:\n"
        f"Fuente: {policy.get('module_id')} | Loader: {policy.get('version')}\n\n"

        "Responsabilidades permitidas para OpenAI:\n"
        f"{_format_list_as_bullets(allowed)}\n\n"

        "Responsabilidades prohibidas para OpenAI:\n"
        f"{_format_list_as_bullets(forbidden)}\n\n"

        "Conceptos runtime que debe respetar:\n"
        f"{_format_list_as_bullets(concepts)}\n\n"

        "Regla final:\n"
        "- OpenAI solo interpreta la necesidad del cliente.\n"
        "- OpenAI no recomienda producto final.\n"
        "- OpenAI no inventa información comercial.\n"
        "- OpenAI no inventa líneas, familias, marcas ni códigos.\n"
        "- Los libros industriales solo aportan contexto técnico.\n"
        "- El catálogo real de VIA es la única fuente para productos, precio, stock y disponibilidad."
    )