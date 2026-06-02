# ============================================================
# services/ai.py
# ============================================================
# RESPONSABILIDAD:
# Capa segura y controlada de OpenAI para NIA.
#
# Este archivo NO es el cerebro de NIA.
# Este archivo NO decide el flujo comercial.
# Este archivo NO reemplaza NIA OS.
#
# NIA OS, el orquestador, memoria, catálogo, guardrails y response
# engine siguen siendo responsables del comportamiento comercial.
#
# Esta capa solo debe:
# - leer configuración OpenAI;
# - crear cliente OpenAI bajo demanda;
# - verificar disponibilidad;
# - ejecutar llamadas seguras cuando el orquestador lo autorice;
# - registrar uso básico sin filtrar secretos;
# - devolver fallbacks seguros si OpenAI está apagado.
#
# Variables esperadas:
# - OPENAI_API_KEY
# - OPENAI_ENABLED
# - OPENAI_MODEL
# - OPENAI_TIMEOUT_SECONDS
# ============================================================

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from openai import OpenAI

from services.audit import registrar_traza_azure

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 20.0
AI_SERVICE_VERSION = "openai_service_v1"


_client: Optional[OpenAI] = None


# ============================================================
# UTILIDADES INTERNAS
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
    Convierte texto de variables de entorno a booleano.
    """
    text = _safe_str(value).lower()

    return text in {"true", "1", "yes", "y", "si", "sí", "on"}


def _parse_float(value: Any, default: float) -> float:
    """
    Convierte un valor a float seguro.
    """
    text = _safe_str(value)

    if not text:
        return default

    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _registrar_traza_segura(etapa: str, payload: Dict[str, Any]) -> None:
    """
    Registra trazas sin afectar el flujo principal.
    Nunca debe romper NIA si el logger falla.
    """
    try:
        registrar_traza_azure(etapa, payload)
    except Exception as error:
        logger.warning("No se pudo registrar traza OpenAI %s: %s", etapa, error)


def _extract_usage(response: Any) -> Dict[str, Any]:
    """
    Extrae usage de una respuesta OpenAI de forma compatible.
    """
    usage = getattr(response, "usage", None)

    if usage is None:
        return {}

    if hasattr(usage, "model_dump"):
        try:
            data = usage.model_dump(exclude_none=True)
            return data if isinstance(data, dict) else {}
        except TypeError:
            data = usage.model_dump()
            return data if isinstance(data, dict) else {}

    if isinstance(usage, dict):
        return {key: value for key, value in usage.items() if value is not None}

    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


# ============================================================
# CONFIGURACIÓN
# ============================================================

def get_openai_config() -> Dict[str, Any]:
    """
    Lee la configuración OpenAI desde variables de entorno.

    No expone la API key.
    """
    api_key = _safe_str(os.getenv("OPENAI_API_KEY"))
    enabled = _parse_bool(os.getenv("OPENAI_ENABLED", "false"))
    model = _safe_str(os.getenv("OPENAI_MODEL"), DEFAULT_OPENAI_MODEL)
    timeout_seconds = _parse_float(
        os.getenv("OPENAI_TIMEOUT_SECONDS"),
        DEFAULT_OPENAI_TIMEOUT_SECONDS,
    )

    missing = []

    if not api_key:
        missing.append("OPENAI_API_KEY")

    if not model:
        missing.append("OPENAI_MODEL")

    ready = enabled and not missing

    return {
        "service_version": AI_SERVICE_VERSION,
        "enabled": enabled,
        "ready": ready,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "api_key_configured": bool(api_key),
        "missing": missing,
    }


def is_openai_enabled() -> bool:
    """
    Indica si OpenAI está habilitado y con configuración suficiente.
    """
    return get_openai_config().get("ready") is True


def get_ai_client() -> OpenAI:
    """
    Retorna cliente OpenAI reutilizable.

    Falla si OPENAI_API_KEY no está configurada.
    No valida OPENAI_ENABLED porque puede usarse para health interno,
    pero las funciones de generación sí deben respetar la bandera.
    """
    global _client

    if _client is None:
        api_key = _safe_str(os.getenv("OPENAI_API_KEY"))

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY no configurado. "
                "Configúralo en .env local o Azure App Service."
            )

        timeout_seconds = _parse_float(
            os.getenv("OPENAI_TIMEOUT_SECONDS"),
            DEFAULT_OPENAI_TIMEOUT_SECONDS,
        )

        _client = OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
        )

        logger.info("Cliente OpenAI inicializado. Timeout=%s", timeout_seconds)

    return _client


def openai_health() -> Dict[str, Any]:
    """
    Diagnóstico seguro de OpenAI sin llamar a la API.
    """
    config = get_openai_config()

    return {
        "ok": config.get("api_key_configured") is True,
        "service_version": AI_SERVICE_VERSION,
        "enabled": config.get("enabled"),
        "ready": config.get("ready"),
        "model": config.get("model"),
        "timeout_seconds": config.get("timeout_seconds"),
        "api_key_configured": config.get("api_key_configured"),
        "missing": config.get("missing"),
    }


# ============================================================
# RESPUESTA ASISTIDA CONTROLADA
# ============================================================

def build_safe_system_instructions() -> str:
    """
    Instrucciones seguras para llamadas OpenAI controladas.

    No reemplaza NIA OS.
    Solo establece límites para que OpenAI no invente información.
    """
    return (
        "Eres una capa auxiliar de redacción e interpretación para NIA, "
        "asistente comercial de VIA Industrial.\n"
        "No eres el cerebro principal del sistema.\n"
        "Debes respetar estas reglas:\n"
        "- No inventes precios.\n"
        "- No inventes disponibilidad.\n"
        "- No inventes tiempos de entrega.\n"
        "- No inventes productos que no estén en el contexto entregado.\n"
        "- Si falta información, dilo de forma segura.\n"
        "- Haz máximo una pregunta concreta si necesitas aclaración.\n"
        "- Mantén tono comercial, claro y breve.\n"
        "- Usa únicamente el contexto permitido por NIA."
    )


def generate_assisted_response(
    *,
    user_message: str,
    safe_context: str = "",
    task: str = "redactar_respuesta_segura",
    fallback_response: str = "",
) -> Dict[str, Any]:
    """
    Genera una respuesta asistida por OpenAI de forma controlada.

    Esta función:
    - Respeta OPENAI_ENABLED.
    - No se ejecuta si OpenAI está apagado.
    - No debe recibir secretos.
    - No debe recibir todo el estado interno de NIA.
    - Solo recibe contexto seguro preparado por el orquestador.

    Retorna dict para que el orquestador decida si usa o no la respuesta.
    """
    config = get_openai_config()

    if not config.get("ready"):
        return {
            "ok": False,
            "used_openai": False,
            "service_version": AI_SERVICE_VERSION,
            "reason": "openai_disabled_or_not_ready",
            "config": {
                "enabled": config.get("enabled"),
                "ready": config.get("ready"),
                "model": config.get("model"),
                "api_key_configured": config.get("api_key_configured"),
                "missing": config.get("missing"),
            },
            "response": fallback_response,
        }

    message = _safe_str(user_message)
    context = _safe_str(safe_context)
    selected_task = _safe_str(task, "redactar_respuesta_segura")

    if not message:
        return {
            "ok": False,
            "used_openai": False,
            "service_version": AI_SERVICE_VERSION,
            "reason": "empty_user_message",
            "response": fallback_response,
        }

    instructions = build_safe_system_instructions()

    input_text = (
        f"TAREA: {selected_task}\n\n"
        f"MENSAJE DEL CLIENTE:\n{message}\n\n"
        f"CONTEXTO SEGURO DISPONIBLE:\n{context if context else 'Sin contexto adicional.'}\n\n"
        "RESPONDE EN ESPAÑOL. No agregues datos no presentes en el contexto."
    )

    try:
        response = get_ai_client().responses.create(
            model=config.get("model") or DEFAULT_OPENAI_MODEL,
            instructions=instructions,
            input=input_text,
            temperature=0.2,
            max_output_tokens=450,
        )

        text = _safe_str(getattr(response, "output_text", ""))

        usage = _extract_usage(response)

        trace_payload = {
            "service_version": AI_SERVICE_VERSION,
            "model": getattr(response, "model", config.get("model")),
            "response_id": getattr(response, "id", None),
            "task": selected_task,
            "usage": usage,
            "used_openai": True,
        }

        _registrar_traza_segura("openai_response_engine.usage", trace_payload)

        if not text:
            return {
                "ok": False,
                "used_openai": True,
                "service_version": AI_SERVICE_VERSION,
                "reason": "empty_model_response",
                "response": fallback_response,
                "usage": usage,
            }

        return {
            "ok": True,
            "used_openai": True,
            "service_version": AI_SERVICE_VERSION,
            "reason": None,
            "model": getattr(response, "model", config.get("model")),
            "response_id": getattr(response, "id", None),
            "response": text,
            "usage": usage,
        }

    except Exception as error:
        logger.exception("Error generando respuesta asistida con OpenAI")

        _registrar_traza_segura(
            "openai_response_engine.error",
            {
                "service_version": AI_SERVICE_VERSION,
                "model": config.get("model"),
                "task": selected_task,
                "error": str(error),
            },
        )

        return {
            "ok": False,
            "used_openai": False,
            "service_version": AI_SERVICE_VERSION,
            "reason": "openai_exception",
            "error": str(error),
            "response": fallback_response,
        }