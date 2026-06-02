# ============================================================
# integrations/bitrix_client.py
# ============================================================
# RESPONSABILIDAD:
# Cliente seguro para futura integración con Bitrix.
#
# Estado actual:
# - NO envía nada por defecto.
# - Usa BITRIX_ENABLED=false como modo seguro.
# - Genera preview usando integrations/bitrix_mapper.py.
# - Solo quedará listo para envío real cuando existan:
#   - BITRIX_ENABLED=true
#   - BITRIX_WEBHOOK_URL
#   - BITRIX_RESPONSIBLE_ID
#
# Importante:
# Este módulo está preparado para integración futura, pero
# en esta fase NO debemos crear tareas reales en Bitrix.
# ============================================================

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from integrations.bitrix_mapper import (
    map_opportunity_to_bitrix_preview,
    map_opportunity_to_bitrix_task_payload,
)


BITRIX_CLIENT_VERSION = "bitrix_client_v1"


# ============================================================
# UTILIDADES DE CONFIGURACIÓN
# ============================================================

def _safe_str(value: Any, default: str = "") -> str:
    """
    Convierte un valor a string seguro.
    """
    if value in [None, "", [], {}]:
        return default

    try:
        text = str(value).strip()
        return text if text else default
    except Exception:
        return default


def _parse_bool(value: Any) -> bool:
    """
    Convierte variables tipo texto a booleano.

    Valores aceptados como True:
    - true
    - 1
    - yes
    - y
    - si
    - sí
    - on

    Cualquier otro valor se considera False.
    """
    text = _safe_str(value).lower()

    return text in {"true", "1", "yes", "y", "si", "sí", "on"}


def _parse_optional_int(value: Any) -> Optional[int]:
    """
    Convierte un valor a entero opcional.
    Si no es convertible, retorna None.
    """
    text = _safe_str(value)

    if not text:
        return None

    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def get_bitrix_config() -> Dict[str, Any]:
    """
    Lee configuración Bitrix desde variables de entorno.

    Variables esperadas:
    - BITRIX_ENABLED
    - BITRIX_WEBHOOK_URL
    - BITRIX_RESPONSIBLE_ID

    No lanza excepción si faltan variables.
    Devuelve diagnóstico seguro.
    """
    enabled = _parse_bool(os.getenv("BITRIX_ENABLED", "false"))
    webhook_url = _safe_str(os.getenv("BITRIX_WEBHOOK_URL"))
    responsible_id = _parse_optional_int(os.getenv("BITRIX_RESPONSIBLE_ID"))

    missing = []

    if not webhook_url:
        missing.append("BITRIX_WEBHOOK_URL")

    if responsible_id is None:
        missing.append("BITRIX_RESPONSIBLE_ID")

    ready_to_send = enabled and not missing

    return {
        "enabled": enabled,
        "webhook_url_configured": bool(webhook_url),
        # No exponemos el webhook completo para evitar filtraciones.
        "webhook_url": webhook_url if enabled else None,
        "responsible_id": responsible_id,
        "missing": missing,
        "ready_to_send": ready_to_send,
    }


# ============================================================
# CLIENTE PRINCIPAL
# ============================================================

def build_bitrix_task_preview_from_opportunity(
    opportunity: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Genera preview seguro de tarea Bitrix.

    No envía nada.
    Se usa para validar formato antes de activar integración real.
    """
    config = get_bitrix_config()

    preview = map_opportunity_to_bitrix_preview(
        opportunity,
        responsible_id=config.get("responsible_id"),
    )

    return {
        "ok": True,
        "client_version": BITRIX_CLIENT_VERSION,
        "mode": "preview",
        "bitrix_enabled": config.get("enabled"),
        "ready_to_send": config.get("ready_to_send"),
        "missing_config": config.get("missing", []),
        "webhook_url_configured": config.get("webhook_url_configured"),
        "preview": preview,
    }


def create_bitrix_task_from_opportunity(
    opportunity: Dict[str, Any],
    *,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Prepara creación de tarea Bitrix desde una oportunidad comercial.

    Estado actual:
    - Por defecto dry_run=True.
    - Si Bitrix no está habilitado, NO envía.
    - Si falta configuración, NO envía.
    - Si dry_run=True, NO envía.

    En una fase posterior, cuando tengamos webhook/permisos,
    aquí se agregará la llamada HTTP real a Bitrix.
    """
    if not isinstance(opportunity, dict):
        opportunity = {}

    config = get_bitrix_config()

    payload = map_opportunity_to_bitrix_task_payload(
        opportunity,
        responsible_id=config.get("responsible_id"),
    )

    blocked_reasons = []

    if not config.get("enabled"):
        blocked_reasons.append("bitrix_disabled")

    if config.get("missing"):
        blocked_reasons.append("missing_config")

    if dry_run:
        blocked_reasons.append("dry_run_enabled")

    should_send = (
        config.get("ready_to_send") is True
        and dry_run is False
        and not blocked_reasons
    )

    # --------------------------------------------------------
    # Modo seguro actual:
    # No hacemos request HTTP real todavía.
    # --------------------------------------------------------
    if not should_send:
        return {
            "ok": True,
            "client_version": BITRIX_CLIENT_VERSION,
            "sent": False,
            "mode": "dry_run" if dry_run else "blocked",
            "blocked_reasons": blocked_reasons,
            "bitrix_enabled": config.get("enabled"),
            "ready_to_send": config.get("ready_to_send"),
            "missing_config": config.get("missing", []),
            "webhook_url_configured": config.get("webhook_url_configured"),
            "payload": payload,
        }

    # --------------------------------------------------------
    # Futuro envío real:
    # Aquí conectaremos requests/httpx cuando Don Andrés nos dé:
    # - webhook
    # - responsible_id real
    # - confirmación de ambiente
    # --------------------------------------------------------
    return {
        "ok": False,
        "client_version": BITRIX_CLIENT_VERSION,
        "sent": False,
        "mode": "not_implemented",
        "blocked_reasons": ["real_http_send_not_implemented_yet"],
        "bitrix_enabled": config.get("enabled"),
        "ready_to_send": config.get("ready_to_send"),
        "missing_config": config.get("missing", []),
        "webhook_url_configured": config.get("webhook_url_configured"),
        "payload": payload,
    }