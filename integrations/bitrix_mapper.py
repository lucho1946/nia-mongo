# ============================================================
# integrations/bitrix_mapper.py
# ============================================================
# RESPONSABILIDAD:
# Convertir una oportunidad comercial generada por NIA
# en un payload preparado para Bitrix.
#
# Este módulo NO:
# - envía datos a Bitrix;
# - usa webhooks;
# - crea tareas reales;
# - modifica MongoDB;
# - decide conversación.
#
# Solo transforma:
#
# commercial_opportunity
#   -> bitrix_task_payload
#
# Objetivo:
# Dejar listo el formato para que, cuando tengamos permisos
# y webhook de Bitrix, solo falte conectar el cliente HTTP.
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Optional


# ============================================================
# CONFIGURACIÓN BASE
# ============================================================

BITRIX_MAPPER_VERSION = "bitrix_mapper_v1"

DEFAULT_RESPONSIBLE_ID = None

DEFAULT_TASK_PRIORITY = 1
# Bitrix task priority usualmente:
# 0 = baja
# 1 = normal
# 2 = alta


# ============================================================
# UTILIDADES
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte un valor a texto seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def _safe_optional_str(value: Any) -> Optional[str]:
    """
    Convierte valor a string o None.
    """
    text = _safe_str(value)

    return text if text else None


def _format_line(label: str, value: Any) -> str:
    """
    Formatea una línea legible para descripción Bitrix.
    No inventa datos. Si no hay valor, muestra 'No informado'.
    """
    value_text = _safe_str(value, "No informado")
    return f"{label}: {value_text}"


def _build_title(opportunity: Dict[str, Any]) -> str:
    """
    Construye título de tarea para Bitrix.
    """
    tipo = _safe_str(opportunity.get("tipo"), "oportunidad")
    producto_codigo = _safe_str(opportunity.get("producto_codigo"), "sin código")
    cliente = _safe_str(opportunity.get("cliente"), "cliente sin nombre")

    if tipo == "proforma":
        prefix = "Nueva proforma NIA"
    elif tipo == "cotizacion":
        prefix = "Nueva cotización NIA"
    else:
        prefix = "Nueva oportunidad NIA"

    return f"{prefix} - {producto_codigo} - {cliente}"


def _build_description(opportunity: Dict[str, Any]) -> str:
    """
    Construye descripción completa para tarea Bitrix.

    La descripción debe ser útil para el asesor:
    - datos del cliente;
    - datos del producto;
    - estado comercial;
    - trazabilidad NIA.
    """
    lines = [
        "Oportunidad comercial generada por NIA",
        "",
        "=== Cliente ===",
        _format_line("Cliente", opportunity.get("cliente")),
        _format_line("Empresa", opportunity.get("empresa")),
        _format_line("Correo", opportunity.get("correo")),
        _format_line("Teléfono", opportunity.get("telefono")),
        _format_line("NIT", opportunity.get("nit")),
        _format_line("Documento fiscal", opportunity.get("documento_fiscal")),
        "",
        "=== Producto ===",
        _format_line("Código", opportunity.get("producto_codigo")),
        _format_line("Nombre", opportunity.get("producto_nombre")),
        _format_line("Marca", opportunity.get("producto_marca")),
        _format_line("Referencia", opportunity.get("producto_referencia")),
        _format_line("Precio", opportunity.get("producto_precio")),
        _format_line("Disponibilidad", opportunity.get("producto_disponibilidad")),
        _format_line("Tiempo de entrega", opportunity.get("producto_tiempo_entrega")),
        "",
        "=== Proceso comercial ===",
        _format_line("Tipo", opportunity.get("tipo")),
        _format_line("Estado", opportunity.get("estado")),
        _format_line("Estado negociación", opportunity.get("estado_negociacion")),
        _format_line("Estado proceso", opportunity.get("commercial_process_state")),
        _format_line("Siguiente paso", opportunity.get("siguiente_paso")),
        "",
        "=== Trazabilidad NIA ===",
        _format_line("Opportunity ID", opportunity.get("opportunity_id")),
        _format_line("Handoff ID", opportunity.get("handoff_id")),
        _format_line("Session ID", opportunity.get("session_id")),
        _format_line("Canal", opportunity.get("canal")),
        _format_line("Cliente ID", opportunity.get("cliente_id")),
        _format_line("Fuente contacto", opportunity.get("contact_source")),
        _format_line("Schema", opportunity.get("schema_version")),
        _format_line("Creado en", opportunity.get("created_at")),
        _format_line("Actualizado en", opportunity.get("updated_at")),
    ]

    return "\n".join(lines)


def _build_tags(opportunity: Dict[str, Any]) -> list[str]:
    """
    Construye tags para clasificar la tarea en Bitrix.
    """
    tags = ["NIA", "oportunidad_comercial"]

    tipo = _safe_optional_str(opportunity.get("tipo"))
    canal = _safe_optional_str(opportunity.get("canal"))
    estado = _safe_optional_str(opportunity.get("estado"))

    if tipo:
        tags.append(tipo)

    if canal:
        tags.append(f"canal_{canal}")

    if estado:
        tags.append(estado)

    return tags


# ============================================================
# MAPPER PRINCIPAL
# ============================================================

def map_opportunity_to_bitrix_task_payload(
    opportunity: Dict[str, Any],
    *,
    responsible_id: Optional[int] = DEFAULT_RESPONSIBLE_ID,
) -> Dict[str, Any]:
    """
    Convierte una oportunidad comercial NIA en payload tipo tarea Bitrix.

    Importante:
    - No envía nada.
    - Solo genera el JSON.
    - Si no hay responsible_id, lo deja en metadata como pendiente.

    Estructura preparada para futura llamada tipo:
    tasks.task.add
    """
    if not isinstance(opportunity, dict):
        opportunity = {}

    title = _build_title(opportunity)
    description = _build_description(opportunity)
    tags = _build_tags(opportunity)

    fields: Dict[str, Any] = {
        "TITLE": title,
        "DESCRIPTION": description,
        "PRIORITY": DEFAULT_TASK_PRIORITY,
        "TAGS": tags,
    }

    if responsible_id is not None:
        fields["RESPONSIBLE_ID"] = responsible_id

    return {
        "ok": True,
        "mapper_version": BITRIX_MAPPER_VERSION,
        "target": "bitrix",
        "method": "tasks.task.add",
        "ready_to_send": responsible_id is not None,
        "missing": [] if responsible_id is not None else ["responsible_id"],
        "fields": fields,
        "source": {
            "opportunity_id": _safe_optional_str(opportunity.get("opportunity_id")),
            "session_id": _safe_optional_str(opportunity.get("session_id")),
            "schema_version": _safe_optional_str(opportunity.get("schema_version")),
        },
    }


def map_opportunity_to_bitrix_preview(
    opportunity: Dict[str, Any],
    *,
    responsible_id: Optional[int] = DEFAULT_RESPONSIBLE_ID,
) -> Dict[str, Any]:
    """
    Genera vista previa amigable del payload Bitrix.

    Se usa para pruebas internas antes de conectar webhook real.
    """
    payload = map_opportunity_to_bitrix_task_payload(
        opportunity,
        responsible_id=responsible_id,
    )

    fields = payload.get("fields", {})

    return {
        "ok": payload.get("ok", False),
        "ready_to_send": payload.get("ready_to_send", False),
        "missing": payload.get("missing", []),
        "target": payload.get("target"),
        "method": payload.get("method"),
        "title": fields.get("TITLE"),
        "description": fields.get("DESCRIPTION"),
        "tags": fields.get("TAGS", []),
        "source": payload.get("source", {}),
        "raw_payload": payload,
    }
    