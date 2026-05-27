# ============================================================
# knowledge/nia_os_loader.py
# ============================================================
# RESPONSABILIDAD:
# Cargar los JSON del cerebro operativo de NIA compartidos
# 
#
# Este módulo es el puente entre:
# - knowledge/nia_os/module_index.json
# - knowledge/nia_os/router/intent_module_map.json
# - knowledge/nia_os/modules/*.json
#
# Y el resto del sistema:
# - orchestrator
# - dynamic_question_engine
# - guardrails
# - response_engine
#
# IMPORTANTE:
# Este módulo NO decide qué responder.
# Este módulo NO busca productos.
# Este módulo NO modifica memoria.
# Solo carga y entrega configuración/conocimiento.
# ============================================================

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# RUTAS BASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

NIA_OS_DIR = BASE_DIR / "nia_os"
MODULES_DIR = NIA_OS_DIR / "modules"
ROUTER_DIR = NIA_OS_DIR / "router"
PROCESSES_DIR = NIA_OS_DIR / "processes"

MODULE_INDEX_PATH = NIA_OS_DIR / "module_index.json"
INTENT_MODULE_MAP_PATH = ROUTER_DIR / "intent_module_map.json"

COMMERCIAL_SPINE_PROCESS_ID = "process_commercial_spine_v1"

# ============================================================
# MAPEO ENTRE NUESTRO INTENT_ROUTER Y LOS INTENTS DE DON ANDRÉS
# ============================================================
# Nuestro sistema actualmente produce intents como:
# - saludo
# - producto
# - comercial
# - codigo_producto
# - general
#
# El router de Don Andrés usa intents como:
# - saludo
# - consulta_producto_codigo
# - consulta_producto_descripcion
# - pide_precio
# - default
#
# Este mapa permite unir ambos mundos sin romper lo que ya funciona.
# ============================================================

LOCAL_TO_NIA_OS_INTENT = {
    "saludo": "saludo",
    "codigo_producto": "consulta_producto_codigo",
    "producto": "consulta_producto_descripcion",
    "comercial": "pide_precio",
    "general": "default",
}


# ============================================================
# UTILIDADES
# ============================================================

def _read_json(path: Path) -> Any:
    """
    Lee un archivo JSON y devuelve su contenido.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo requerido: {path}"
        )

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _safe_list(value: Any) -> List[Any]:
    """
    Convierte un valor a lista segura.
    """
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


# ============================================================
# CARGA PRINCIPAL CON CACHE
# ============================================================
# Usamos cache para no leer los JSON del disco en cada mensaje.
# Si modificas un JSON y quieres recargar en caliente, puedes llamar
# clear_nia_os_cache().
# ============================================================

@lru_cache(maxsize=1)
def load_module_index() -> List[Dict[str, Any]]:
    """
    Carga module_index.json.

    Este archivo lista todos los módulos disponibles,
    su prioridad, versión y descripción.
    """
    data = _read_json(MODULE_INDEX_PATH)

    if not isinstance(data, list):
        raise ValueError(
            "module_index.json debe ser una lista de módulos."
        )

    return data


@lru_cache(maxsize=1)
def load_intent_module_map() -> Dict[str, List[str]]:
    """
    Carga router/intent_module_map.json.

    Este archivo indica qué módulos se activan según la intención.
    """
    data = _read_json(INTENT_MODULE_MAP_PATH)

    if not isinstance(data, dict):
        raise ValueError(
            "intent_module_map.json debe ser un objeto JSON."
        )

    normalized = {}

    for intent, modules in data.items():
        normalized[str(intent)] = [
            str(module_id)
            for module_id in _safe_list(modules)
        ]

    return normalized


@lru_cache(maxsize=64)
def load_module_by_file(file_name: str) -> Dict[str, Any]:
    """
    Carga un módulo JSON usando su nombre de archivo.
    """
    path = MODULES_DIR / file_name

    data = _read_json(path)

    if not isinstance(data, dict):
        raise ValueError(
            f"El módulo {file_name} debe ser un objeto JSON."
        )

    return data


@lru_cache(maxsize=64)
def load_module_by_id(module_id: str) -> Optional[Dict[str, Any]]:
    """
    Carga un módulo JSON usando su module_id.
    """
    module_index = load_module_index()

    for module_info in module_index:
        if module_info.get("module_id") == module_id:
            file_name = module_info.get("file")

            if not file_name:
                return None

            return load_module_by_file(file_name)

    return None

# ============================================================
# CARGA DE PROCESOS NIA OS
# ============================================================

@lru_cache(maxsize=64)
def load_process_by_file(file_name: str) -> Dict[str, Any]:
    """
    Carga un proceso JSON desde knowledge/nia_os/processes/.

    Los procesos NO reemplazan módulos.
    Los procesos ordenan módulos y definen flujos maestros.
    """
    path = PROCESSES_DIR / file_name

    data = _read_json(path)

    if not isinstance(data, dict):
        raise ValueError(
            f"El proceso {file_name} debe ser un objeto JSON."
        )

    return data


@lru_cache(maxsize=1)
def load_all_processes() -> List[Dict[str, Any]]:
    """
    Carga todos los procesos JSON disponibles en knowledge/nia_os/processes/.
    """
    if not PROCESSES_DIR.exists():
        return []

    processes: List[Dict[str, Any]] = []

    for path in sorted(PROCESSES_DIR.glob("*.json")):
        process = load_process_by_file(path.name)

        if process:
            processes.append(process)

    return processes


@lru_cache(maxsize=64)
def load_process_by_id(process_id: str) -> Optional[Dict[str, Any]]:
    """
    Busca un proceso por process_id.
    """
    process_id = str(process_id or "").strip()

    if not process_id:
        return None

    for process in load_all_processes():
        if process.get("process_id") == process_id:
            return process

    return None


def get_available_processes() -> List[Dict[str, Any]]:
    """
    Devuelve todos los procesos disponibles.
    """
    return load_all_processes()


def get_process(process_id: str) -> Optional[Dict[str, Any]]:
    """
    Devuelve un proceso por ID.
    """
    return load_process_by_id(process_id)


def get_commercial_spine_process() -> Dict[str, Any]:
    """
    Devuelve la columna vertebral comercial de NIA.

    Este proceso define el flujo maestro comercial:
    mensaje → memoria → intención → estado → acción → respuesta → nuevo estado.
    """
    process = load_process_by_id(COMMERCIAL_SPINE_PROCESS_ID)

    if not process:
        return {}

    return process


# ============================================================
# CONSULTAS DE MÓDULOS
# ============================================================

def get_available_modules() -> List[Dict[str, Any]]:
    """
    Devuelve la lista de módulos disponibles según module_index.json.
    """
    return load_module_index()


def get_module_ids_for_intent(intent: str) -> List[str]:
    """
    Devuelve los module_id asociados a una intención.

    Acepta tanto intents internos del proyecto como intents
    del router de Don Andrés.
    """
    intent = intent or "general"

    nia_os_intent = LOCAL_TO_NIA_OS_INTENT.get(
        intent,
        intent,
    )

    intent_map = load_intent_module_map()

    return intent_map.get(
        nia_os_intent,
        intent_map.get("default", []),
    )


def get_modules_for_intent(intent: str) -> List[Dict[str, Any]]:
    """
    Devuelve los módulos completos asociados a una intención.
    """
    module_ids = get_module_ids_for_intent(intent)

    modules: List[Dict[str, Any]] = []

    for module_id in module_ids:
        module = load_module_by_id(module_id)

        if module:
            modules.append(module)

    return modules


def get_module(module_id: str) -> Optional[Dict[str, Any]]:
    """
    Devuelve un módulo por ID.
    """
    return load_module_by_id(module_id)


# ============================================================
# REGLAS TRANSVERSALES
# ============================================================

def get_guardrails_rules() -> List[str]:
    """
    Devuelve las reglas del módulo guardrails/no inventar.
    """
    module = load_module_by_id(
        "module_guardrails_no_inventar"
    )

    if not module:
        return []

    return module.get("reglas", [])


def get_memory_rules() -> List[str]:
    """
    Devuelve reglas del módulo de memoria contextual.
    """
    module = load_module_by_id(
        "module_memoria_contextual"
    )

    if not module:
        return []

    return module.get("reglas", [])


def get_api_product_rules() -> Dict[str, Any]:
    """
    Devuelve configuración del módulo API de productos.
    """
    module = load_module_by_id(
        "module_motor_api_productos"
    )

    if not module:
        return {}

    return {
        "regla_maestra": module.get("regla_maestra", []),
        "deteccion_prioritaria": module.get("deteccion_prioritaria", []),
        "flujo": module.get("flujo", []),
        "formato_respuesta_producto": module.get(
            "formato_respuesta_producto",
            [],
        ),
    }


def get_technical_product_rules() -> Dict[str, Any]:
    """
    Devuelve reglas del motor técnico de producto.
    """
    module = load_module_by_id(
        "module_motor_tecnico_producto"
    )

    if not module:
        return {}

    return {
        "variables_tecnicas_minimas": module.get(
            "variables_tecnicas_minimas",
            [],
        ),
        "reglas": module.get("reglas", []),
    }


def get_commercial_rules() -> Dict[str, Any]:
    """
    Devuelve reglas del motor comercial.
    """
    module = load_module_by_id(
        "module_motor_comercial"
    )

    if not module:
        return {}

    return module


def get_price_quote_rules() -> Dict[str, Any]:
    """
    Devuelve reglas del motor de cotización, precio y disponibilidad.
    """
    module = load_module_by_id(
        "module_motor_cotizacion_precio"
    )

    if not module:
        return {}

    return module


# ============================================================
# RESUMEN OPERATIVO
# ============================================================

def build_nia_os_context(intent: str) -> Dict[str, Any]:
    """
    Construye una vista compacta de los módulos que aplican
    para una intención específica.

    Esto será útil después para que el orchestrator sepa:
    - qué módulos se activan
    - qué reglas transversales aplicar
    - qué flujo de API respetar
    """
    module_ids = get_module_ids_for_intent(intent)
    modules = get_modules_for_intent(intent)

    commercial_spine = get_commercial_spine_process()

    return {
        "input_intent": intent,
        "nia_os_intent": LOCAL_TO_NIA_OS_INTENT.get(
            intent,
            intent,
        ),
        "module_ids": module_ids,
        "modules": modules,
        "guardrails": get_guardrails_rules(),
        "memory_rules": get_memory_rules(),
        "api_product_rules": get_api_product_rules(),
        "technical_product_rules": get_technical_product_rules(),

        # Proceso maestro comercial.
        # Por ahora se expone como metadata segura para que luego
        # el orquestador pueda usar sus estados y reglas.
        "commercial_spine": commercial_spine,
    }


# ============================================================
# CACHE
# ============================================================

def clear_nia_os_cache() -> None:
    """
    Limpia cache de carga de JSON.

    Útil si editas archivos JSON y quieres que Python los recargue
    sin reiniciar el proceso.
    """
    load_module_index.cache_clear()
    load_intent_module_map.cache_clear()
    load_module_by_file.cache_clear()
    load_module_by_id.cache_clear()
    load_process_by_file.cache_clear()
    load_all_processes.cache_clear()
    load_process_by_id.cache_clear()


# ============================================================
# VALIDACIÓN
# ============================================================

def validate_nia_os_files() -> Dict[str, Any]:
    """
    Valida que existan los archivos principales y que los módulos
    declarados en module_index.json estén disponibles.
    """
    errors: List[str] = []

    if not MODULE_INDEX_PATH.exists():
        errors.append(f"No existe {MODULE_INDEX_PATH}")

    if not INTENT_MODULE_MAP_PATH.exists():
        errors.append(f"No existe {INTENT_MODULE_MAP_PATH}")

    module_index = []

    try:
        module_index = load_module_index()
    except Exception as exc:
        errors.append(f"Error cargando module_index.json: {exc}")

    for module_info in module_index:
        file_name = module_info.get("file")

        if not file_name:
            errors.append(
                f"Módulo sin campo file: {module_info}"
            )
            continue

        module_path = MODULES_DIR / file_name

        if not module_path.exists():
            errors.append(
                f"No existe módulo declarado en index: {module_path}"
            )

    try:
        load_intent_module_map()
    except Exception as exc:
        errors.append(
            f"Error cargando intent_module_map.json: {exc}"
        )
    
    processes = []

    if not PROCESSES_DIR.exists():
        errors.append(f"No existe carpeta de procesos: {PROCESSES_DIR}")
    else:
        try:
            processes = load_all_processes()
        except Exception as exc:
            errors.append(f"Error cargando procesos NIA OS: {exc}")

    commercial_spine = {}

    try:
        commercial_spine = get_commercial_spine_process()
    except Exception as exc:
        errors.append(f"Error cargando commercial spine: {exc}")

    if not commercial_spine:
        errors.append(
            f"No se encontró proceso requerido: {COMMERCIAL_SPINE_PROCESS_ID}"
        )
    else:
        required_keys = [
            "process_id",
            "name",
            "version",
            "purpose",
            "master_flow",
            "golden_rules",
            "minimal_memory_fields",
            "response_policy",
        ]

        for key in required_keys:
            if key not in commercial_spine:
                errors.append(
                    f"Commercial spine sin clave requerida: {key}"
                )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "module_count": len(module_index),
        "process_count": len(processes),
        "commercial_spine_loaded": bool(commercial_spine),
        "base_path": str(NIA_OS_DIR),
    }


# ============================================================
# DEBUG LOCAL
# ============================================================

if __name__ == "__main__":
    validation = validate_nia_os_files()

    print("=" * 60)
    print("NIA OS LOADER VALIDATION")
    print("=" * 60)
    print(validation)

    print("\nMódulos para intent producto:")
    print(get_module_ids_for_intent("producto"))

    print("\nMódulos para intent comercial:")
    print(get_module_ids_for_intent("comercial"))

    print("\nGuardrails:")
    for rule in get_guardrails_rules():
        print("-", rule)