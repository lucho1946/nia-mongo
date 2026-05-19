# ============================================================
# services/audit.py
# Responsabilidad única:
# - registrar trazas JSONL del flujo end to end de NIA
# - dejar evidencia de inputs y outputs hacia Azure OpenAI
# - facilitar debugging en Azure App Service y en local
# ============================================================

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Carpeta de logs local del proyecto.
# En Azure también funcionará si el entorno permite escritura.
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

AZURE_LOG_FILE = LOG_DIR / "azure_inputs.jsonl"


def registrar_traza_azure(etapa: str, payload: dict[str, Any]) -> None:
    """
    Registra una traza estructurada en formato JSONL.

    Parámetros:
    - etapa: nombre del evento ("chat.input", "decidir_accion.input", etc.)
    - payload: diccionario con el contexto que queremos rastrear

    Hace dos cosas:
    1) lo manda al logger para Azure App Service
    2) lo guarda en archivo JSONL local
    """
    evento = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "etapa": etapa,
        **payload,
    }

    linea = json.dumps(evento, ensure_ascii=False, default=str)

    # Esto aparece en Azure Log Stream / App Service logs
    logger.info("[AZURE_TRACE] %s", linea)

    # Esto deja un archivo persistente en logs/
    with AZURE_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")