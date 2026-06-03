# ============================================================
# knowledge/nia_os_integration_audit.py
# ============================================================
# RESPONSABILIDAD:
# Auditar el nivel real de integración de los módulos de NIA OS.
#
# Este archivo NO modifica comportamiento de producción.
# Este archivo NO llama OpenAI.
# Este archivo NO consulta MongoDB.
# Este archivo NO toca Bitrix.
# Este archivo NO responde al cliente.
#
# Objetivo:
# Saber si cada módulo de NIA OS está:
# - declarado en module_index.json;
# - cargable desde knowledge/nia_os/modules/;
# - mapeado por intención;
# - usado por process_commercial_spine_v1;
# - conectado a runtime Python;
# - activo, parcial, solo declarado o faltante.
#
# Esto nos permite integrar NIA OS módulo por módulo, con evidencia.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Optional

from knowledge.nia_os_loader import (
    MODULES_DIR,
    load_module_index,
    load_intent_module_map,
    load_module_by_id,
    get_commercial_spine_process,
    validate_nia_os_files,
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

AUDIT_VERSION = "nia_os_integration_audit_v1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ============================================================
# EVIDENCIA DE RUNTIME PYTHON
# ============================================================
# Esta matriz NO decide si un módulo funciona perfecto.
# Solo busca evidencia de que existe código Python conectado
# con la responsabilidad del módulo.
#
# Importante:
# - Si un archivo no existe, no rompe el audit.
# - Si existe, cuenta como evidencia de integración runtime.
# - Esto es diagnóstico, no ejecución.
# ============================================================

RUNTIME_EVIDENCE_MAP: Dict[str, List[Dict[str, str]]] = {
    "module_motor_comercial": [
        {
            "path": "orchestration/commercial_continuity.py",
            "reason": "continuidad comercial con producto activo, cotización y seguimiento",
        },
        {
            "path": "orchestration/commercial_state_engine.py",
            "reason": "estado comercial y avance del proceso",
        },
        {
            "path": "core/intent_router.py",
            "reason": "detección inicial de intención comercial",
        },
    ],
    "module_motor_tecnico_producto": [
        {
            "path": "knowledge/dynamic_question_engine.py",
            "reason": "preguntas técnicas dinámicas según contexto",
        },
        {
            "path": "knowledge/catalog_knowledge.py",
            "reason": "extracción de conocimiento técnico desde producto real",
        },
        {
            "path": "orchestration/nia_orchestrator.py",
            "reason": "validación de compatibilidad producto/intención",
        },
    ],
    "module_motor_api_productos": [
        {
            "path": "retrieval/search_adapter.py",
            "reason": "adaptador de búsqueda usado por el orquestador",
        },
        {
            "path": "services/search.py",
            "reason": "búsqueda real en catálogo Mongo/RapidFuzz",
        },
        {
            "path": "routers/productos.py",
            "reason": "endpoints /producto/{codigo}, /buscar, /health y /resumen",
        },
    ],
    "module_vision_archivos": [
        {
            "path": "routers/uploads.py",
            "reason": "endpoint de carga de archivos",
        },
        {
            "path": "services/multimodal.py",
            "reason": "procesamiento multimodal de imágenes/PDF/archivos",
        },
    ],
    "module_motor_cotizacion_precio": [
        {
            "path": "orchestration/commercial_continuity.py",
            "reason": "flujo de cotización desde producto activo",
        },
        {
            "path": "orchestration/commercial_handoff.py",
            "reason": "estructura datos comerciales para asesor/cotización",
        },
    ],
    "module_motor_cierre_proforma": [
        {
            "path": "orchestration/commercial_proforma.py",
            "reason": "flujo de cierre/proforma cuando hay intención de compra",
        },
    ],
    "module_motor_soporte_tecnico": [
        {
            "path": "knowledge/document_policy.py",
            "reason": "política documental para decidir cuándo aplicar soporte técnico documental",
        },
        {
            "path": "retrieval/document_store_retriever.py",
            "reason": "retrieval documental preparado para soporte técnico",
        },
    ],
    "module_guardrails_no_inventar": [
        {
            "path": "knowledge/response_guardrails.py",
            "reason": "validación de respuesta para evitar invención",
        },
        {
            "path": "orchestration/nia_os_runtime_policy.py",
            "reason": "política ejecutable derivada desde NIA OS",
        },
    ],
    "module_memoria_contextual": [
        {
            "path": "memory/conversation_memory.py",
            "reason": "memoria de sesión, contexto, producto activo y mensajes",
        },
    ],
    "module_estado_negociacion": [
        {
            "path": "orchestration/commercial_state_engine.py",
            "reason": "motor de estado del proceso comercial",
        },
    ],
    "module_observabilidad": [
        {
            "path": "services/audit.py",
            "reason": "registro de trazas Azure/eventos internos",
        },
        {
            "path": "routers/chat.py",
            "reason": "trazabilidad de entrada y salida del endpoint /chat",
        },
    ],
    "module_hibrido_humano_ia": [
        {
            "path": "orchestration/commercial_handoff.py",
            "reason": "handoff comercial hacia asesor humano",
        },
        {
            "path": "routers/commercial_opportunities.py",
            "reason": "consulta/preview/dry-run de oportunidades para CRM/asesor",
        },
    ],
}


# ============================================================
# UTILIDADES
# ============================================================

def _safe_list(value: Any) -> List[Any]:
    """
    Convierte cualquier valor en lista segura.
    """
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _unique_sorted(values: List[str] | Set[str]) -> List[str]:
    """
    Devuelve lista única ordenada.
    """
    return sorted({str(value) for value in values if value not in [None, ""]})


def _path_exists(relative_path: str) -> bool:
    """
    Verifica si existe una ruta relativa al root del proyecto.
    """
    return (PROJECT_ROOT / relative_path).exists()


def _read_text_file_if_exists(relative_path: str) -> str:
    """
    Lee un archivo de texto si existe. Si no existe, retorna string vacío.
    """
    path = PROJECT_ROOT / relative_path

    if not path.exists() or not path.is_file():
        return ""

    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _collect_module_ids_from_any_json(value: Any) -> Set[str]:
    """
    Recorre cualquier estructura JSON y extrae valores tipo module_*.

    Esto permite detectar módulos usados en:
    - existing_modules_used
    - uses_modules
    - cualquier lista o campo futuro donde aparezca un module_id
    """
    found: Set[str] = set()

    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and item.startswith("module_"):
                found.add(item)

            if isinstance(item, list):
                for element in item:
                    if isinstance(element, str) and element.startswith("module_"):
                        found.add(element)

            found.update(_collect_module_ids_from_any_json(item))

    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.startswith("module_"):
                found.add(item)

            found.update(_collect_module_ids_from_any_json(item))

    elif isinstance(value, str):
        if value.startswith("module_"):
            found.add(value)

    return found


def _collect_module_ids_from_intent_map(intent_map: Dict[str, List[str]]) -> Set[str]:
    """
    Extrae todos los module_id usados por intent_module_map.json.
    """
    module_ids: Set[str] = set()

    for modules in intent_map.values():
        for module_id in _safe_list(modules):
            if isinstance(module_id, str) and module_id.startswith("module_"):
                module_ids.add(module_id)

    return module_ids


def _collect_intents_by_module(intent_map: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """
    Construye un índice inverso:

    module_id -> [intents donde aparece]
    """
    index: Dict[str, List[str]] = {}

    for intent, modules in intent_map.items():
        for module_id in _safe_list(modules):
            if not isinstance(module_id, str):
                continue

            index.setdefault(module_id, []).append(intent)

    return {
        module_id: sorted(intents)
        for module_id, intents in index.items()
    }


def _evaluate_runtime_evidence(module_id: str) -> Dict[str, Any]:
    """
    Evalúa si hay evidencia de runtime Python para un módulo.

    Devuelve:
    - configured_evidence: lo que esperamos revisar;
    - existing_evidence: archivos que existen;
    - missing_evidence: archivos esperados que no existen;
    - has_runtime_hint: true si hay al menos una evidencia existente.
    """
    expected = RUNTIME_EVIDENCE_MAP.get(module_id, [])

    existing: List[Dict[str, str]] = []
    missing: List[Dict[str, str]] = []

    for item in expected:
        relative_path = item.get("path", "")

        if not relative_path:
            continue

        if _path_exists(relative_path):
            existing.append(item)
        else:
            missing.append(item)

    return {
        "configured_evidence": expected,
        "existing_evidence": existing,
        "missing_evidence": missing,
        "has_runtime_hint": len(existing) > 0,
    }


def _detect_module_mentions_in_runtime(module_id: str) -> List[str]:
    """
    Busca menciones literales del module_id en archivos Python clave.

    Esto NO reemplaza la evidencia de runtime.
    Sirve como señal adicional para saber si el module_id se usa explícitamente.
    """
    python_paths = [
        "orchestration/nia_orchestrator.py",
        "orchestration/nia_os_runtime_policy.py",
        "orchestration/commercial_state_engine.py",
        "orchestration/commercial_continuity.py",
        "orchestration/commercial_proforma.py",
        "orchestration/commercial_handoff.py",
        "knowledge/nia_os_loader.py",
        "knowledge/response_guardrails.py",
        "routers/chat.py",
        "routers/uploads.py",
        "routers/commercial_opportunities.py",
        "services/audit.py",
    ]

    mentions: List[str] = []

    for relative_path in python_paths:
        content = _read_text_file_if_exists(relative_path)

        if module_id in content:
            mentions.append(relative_path)

    return sorted(mentions)


def _classify_integration_level(
    *,
    declared_in_index: bool,
    loadable: bool,
    mapped_in_intents: bool,
    used_in_commercial_spine: bool,
    has_runtime_hint: bool,
    explicitly_mentioned_in_runtime: bool,
) -> str:
    """
    Clasifica el estado de integración de un módulo.

    Niveles:
    - missing:
      Algo está roto. El módulo no está declarado o no carga.

    - declared_only:
      Existe, pero no está conectado a intents, proceso ni runtime.

    - mapped_only:
      Está en mapa/proceso, pero no hay evidencia runtime.

    - runtime_without_spine:
      Tiene código Python y está mapeado por intención, pero no aparece
      en process_commercial_spine_v1.json. Esto significa que existe
      runtime, pero todavía no está gobernado por la columna comercial.

    - partial:
      Tiene algunas señales, pero no suficientes para considerarlo integrado.

    - active:
      Está declarado, carga, aparece en el proceso comercial y tiene runtime.

    - active_explicit:
      Además de lo anterior, el module_id aparece literalmente en código Python.
    """
    if not declared_in_index or not loadable:
        return "missing"

    if (
        not mapped_in_intents
        and not used_in_commercial_spine
        and not has_runtime_hint
        and not explicitly_mentioned_in_runtime
    ):
        return "declared_only"

    if (
        (mapped_in_intents or used_in_commercial_spine)
        and not has_runtime_hint
        and not explicitly_mentioned_in_runtime
    ):
        return "mapped_only"

    # Caso crítico para nuestra integración:
    # El módulo existe y tiene código, pero no está gobernado por
    # process_commercial_spine_v1.json.
    if has_runtime_hint and mapped_in_intents and not used_in_commercial_spine:
        return "runtime_without_spine"

    if has_runtime_hint and used_in_commercial_spine:
        if explicitly_mentioned_in_runtime:
            return "active_explicit"

        return "active"

    return "partial"


def _build_module_gap_messages(report: Dict[str, Any]) -> List[str]:
    """
    Genera mensajes humanos de brecha para un módulo.
    """
    module_id = report.get("module_id")
    gaps: List[str] = []

    if not report.get("declared_in_index"):
        gaps.append(f"{module_id}: no está declarado en module_index.json.")

    if not report.get("loadable"):
        gaps.append(f"{module_id}: no carga desde knowledge/nia_os/modules/.")

    if not report.get("mapped_in_intents"):
        gaps.append(f"{module_id}: no aparece en intent_module_map.json.")

    if not report.get("used_in_commercial_spine"):
        gaps.append(f"{module_id}: no aparece en process_commercial_spine_v1.json.")

    if not report.get("has_runtime_hint"):
        gaps.append(f"{module_id}: no se detectó evidencia runtime Python configurada.")

    if report.get("integration_level") in ["mapped_only", "partial", "declared_only"]:
        gaps.append(
            f"{module_id}: integración incompleta ({report.get('integration_level')})."
        )

    return gaps


def _build_recommendation(report: Dict[str, Any]) -> str:
    """
    Sugiere siguiente acción para un módulo.
    """
    module_id = report.get("module_id")
    level = report.get("integration_level")

    if level in ["active", "active_explicit"]:
        return "Mantener y crear/fortalecer tests de comportamiento si falta cobertura."

    if level == "missing":
        return "Corregir declaración/carga del módulo antes de avanzar."

    if level == "declared_only":
        return (
            "Definir en qué intención/proceso se debe usar y luego conectar runtime."
        )

    if level == "mapped_only":
        return (
            "Implementar o conectar runtime Python que ejecute la responsabilidad del módulo."
        )

    if level == "runtime_without_spine":
        return (
            "Registrar el módulo en process_commercial_spine_v1.json y crear prueba "
            "que demuestre que la columna comercial lo contempla."
        )

    if level == "partial":
        return (
            "Completar integración: proceso, intención, runtime y prueba end-to-end del módulo."
        )


# ============================================================
# AUDITORÍA PRINCIPAL
# ============================================================

def build_nia_os_integration_audit() -> Dict[str, Any]:
    """
    Construye reporte completo de integración NIA OS.

    No tiene efectos secundarios.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # --------------------------------------------------------
    # 1. Validación base desde loader existente
    # --------------------------------------------------------
    base_validation = validate_nia_os_files()

    if not base_validation.get("ok"):
        errors.extend(base_validation.get("errors", []))

    # --------------------------------------------------------
    # 2. Carga de fuentes NIA OS
    # --------------------------------------------------------
    try:
        module_index = load_module_index()
    except Exception as exc:
        module_index = []
        errors.append(f"Error cargando module_index.json: {exc}")

    try:
        intent_map = load_intent_module_map()
    except Exception as exc:
        intent_map = {}
        errors.append(f"Error cargando intent_module_map.json: {exc}")

    try:
        commercial_spine = get_commercial_spine_process()
    except Exception as exc:
        commercial_spine = {}
        errors.append(f"Error cargando process_commercial_spine_v1: {exc}")

    # --------------------------------------------------------
    # 3. Índices derivados
    # --------------------------------------------------------
    declared_modules: Dict[str, Dict[str, Any]] = {}

    for item in module_index:
        module_id = str(item.get("module_id", "")).strip()

        if not module_id:
            warnings.append(f"Entrada de module_index sin module_id: {item}")
            continue

        declared_modules[module_id] = item

    mapped_module_ids = _collect_module_ids_from_intent_map(intent_map)
    intents_by_module = _collect_intents_by_module(intent_map)

    process_module_ids = _collect_module_ids_from_any_json(commercial_spine)

    module_files_on_disk = sorted(
        path.name for path in MODULES_DIR.glob("*.json")
    ) if MODULES_DIR.exists() else []

    declared_files = {
        str(item.get("file"))
        for item in module_index
        if item.get("file")
    }

    unregistered_module_files = [
        file_name
        for file_name in module_files_on_disk
        if file_name not in declared_files
    ]

    # Módulos referenciados por intent/proceso que no están en module_index.
    referenced_module_ids = mapped_module_ids.union(process_module_ids)

    referenced_but_not_declared = _unique_sorted(
        referenced_module_ids.difference(set(declared_modules.keys()))
    )

    declared_but_not_referenced = _unique_sorted(
        set(declared_modules.keys()).difference(referenced_module_ids)
    )

    all_known_module_ids = _unique_sorted(
        set(declared_modules.keys()).union(referenced_module_ids)
    )

    # --------------------------------------------------------
    # 4. Reporte por módulo
    # --------------------------------------------------------
    module_reports: List[Dict[str, Any]] = []
    all_gap_messages: List[str] = []

    for module_id in all_known_module_ids:
        declared_in_index = module_id in declared_modules

        module_info = declared_modules.get(module_id, {})

        try:
            loaded_module = load_module_by_id(module_id)
            loadable = isinstance(loaded_module, dict)
            load_error = None
        except Exception as exc:
            loaded_module = None
            loadable = False
            load_error = str(exc)

        mapped_in_intents = module_id in mapped_module_ids
        used_in_commercial_spine = module_id in process_module_ids

        runtime_evidence = _evaluate_runtime_evidence(module_id)
        runtime_mentions = _detect_module_mentions_in_runtime(module_id)

        has_runtime_hint = bool(runtime_evidence.get("has_runtime_hint"))
        explicitly_mentioned_in_runtime = len(runtime_mentions) > 0

        integration_level = _classify_integration_level(
            declared_in_index=declared_in_index,
            loadable=loadable,
            mapped_in_intents=mapped_in_intents,
            used_in_commercial_spine=used_in_commercial_spine,
            has_runtime_hint=has_runtime_hint,
            explicitly_mentioned_in_runtime=explicitly_mentioned_in_runtime,
        )

        report = {
            "module_id": module_id,
            "name": module_info.get("nombre_visible"),
            "version": module_info.get("version"),
            "priority": module_info.get("prioridad"),
            "declared_in_index": declared_in_index,
            "declared_file": module_info.get("file"),
            "loadable": loadable,
            "load_error": load_error,
            "mapped_in_intents": mapped_in_intents,
            "intents": intents_by_module.get(module_id, []),
            "used_in_commercial_spine": used_in_commercial_spine,
            "has_runtime_hint": has_runtime_hint,
            "runtime_evidence": runtime_evidence.get("existing_evidence", []),
            "missing_runtime_evidence": runtime_evidence.get("missing_evidence", []),
            "runtime_mentions": runtime_mentions,
            "integration_level": integration_level,
        }

        report["gaps"] = _build_module_gap_messages(report)
        report["recommendation"] = _build_recommendation(report)

        all_gap_messages.extend(report["gaps"])

        module_reports.append(report)

    # Ordenamos por prioridad del índice, dejando desconocidos al final.
    module_reports.sort(
        key=lambda item: (
            999 if item.get("priority") is None else item.get("priority"),
            item.get("module_id", ""),
        )
    )

    # --------------------------------------------------------
    # 5. Resumen
    # --------------------------------------------------------
    levels: Dict[str, int] = {}

    for report in module_reports:
        level = report.get("integration_level", "unknown")
        levels[level] = levels.get(level, 0) + 1

    critical_errors = []

    if referenced_but_not_declared:
        critical_errors.append(
            "Hay módulos referenciados por intent/proceso que no están declarados."
        )

    if unregistered_module_files:
        warnings.append(
            "Hay archivos de módulo en modules/ que no están en module_index.json."
        )

    if declared_but_not_referenced:
        warnings.append(
            "Hay módulos declarados que no están referenciados por intent ni proceso."
        )

    errors.extend(critical_errors)

    # --------------------------------------------------------
    # 6. Candidatos para integración
    # --------------------------------------------------------
    next_integration_candidates = [
    {
        "module_id": report["module_id"],
        "integration_level": report["integration_level"],
        "gaps": report.get("gaps", []),
        "recommendation": report["recommendation"],
    }
    for report in module_reports
    if (
        report.get("integration_level") not in ["active", "active_explicit"]
        or report.get("gaps")
    )
]

    return {
        "ok": len(errors) == 0,
        "version": AUDIT_VERSION,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "module_count_index": len(module_index),
            "module_count_reported": len(module_reports),
            "intent_count": len(intent_map),
            "process_loaded": bool(commercial_spine),
            "levels": levels,
            "unregistered_module_files_count": len(unregistered_module_files),
            "referenced_but_not_declared_count": len(referenced_but_not_declared),
            "declared_but_not_referenced_count": len(declared_but_not_referenced),
        },
        "files": {
            "module_files_on_disk": module_files_on_disk,
            "unregistered_module_files": unregistered_module_files,
        },
        "coverage": {
            "mapped_module_ids": _unique_sorted(mapped_module_ids),
            "process_module_ids": _unique_sorted(process_module_ids),
            "referenced_but_not_declared": referenced_but_not_declared,
            "declared_but_not_referenced": declared_but_not_referenced,
        },
        "modules": module_reports,
        "gaps": _unique_sorted(all_gap_messages),
        "next_integration_candidates": next_integration_candidates,
        "base_validation": base_validation,
    }


# ============================================================
# HELPERS DE CONSULTA
# ============================================================

def get_module_integration_report(module_id: str) -> Optional[Dict[str, Any]]:
    """
    Devuelve el reporte de integración de un módulo específico.
    """
    module_id = str(module_id or "").strip()

    if not module_id:
        return None

    audit = build_nia_os_integration_audit()

    for module_report in audit.get("modules", []):
        if module_report.get("module_id") == module_id:
            return module_report

    return None


def get_modules_by_integration_level(level: str) -> List[Dict[str, Any]]:
    """
    Devuelve módulos filtrados por nivel de integración.
    """
    level = str(level or "").strip()

    audit = build_nia_os_integration_audit()

    return [
        module_report
        for module_report in audit.get("modules", [])
        if module_report.get("integration_level") == level
    ]


# ============================================================
# EJECUCIÓN MANUAL
# ============================================================

def main() -> None:
    """
    Ejecuta la auditoría completa y la imprime en JSON.
    """
    audit = build_nia_os_integration_audit()

    print("=" * 70)
    print("NIA OS INTEGRATION AUDIT")
    print("=" * 70)
    print(json.dumps(audit, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()