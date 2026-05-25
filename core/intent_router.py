# =========================================================
# core/intent_router.py
# =========================================================
# Responsabilidad:
# Detectar intención principal del mensaje del usuario.
#
# Enfoque:
# - Detectar códigos aunque vengan dentro de frases.
# - Detectar saludos puros sin confundir "hola necesito...".
# - Detectar intención comercial natural.
# - Detectar productos industriales aunque el cliente escriba informal.
# =========================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional


# =========================================================
# UTILIDADES
# =========================================================

def _normalize(text: Any) -> str:
    """
    Normaliza texto:
    - minúsculas
    - sin acentos
    - espacios limpios
    """
    text = "" if text is None else str(text)
    text = text.lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text)


def extract_exact_product_code(message: str) -> Optional[str]:
    """
    Extrae un código exacto de producto dentro de una frase.

    Ejemplos:
    - "P382280" -> P382280
    - "busco el P382280" -> P382280
    - "me cotizas el producto 123456" -> 123456

    Evita confundir:
    - 220v
    - 3hp
    - 200nm
    - 16 entradas
    """
    raw = str(message or "").strip()

    if not raw:
        return None

    # Código VIA tipo P382280, incluso dentro de una frase.
    match_p = re.search(
        r"\b(P[0-9]{4,}[A-Za-z0-9]*)\b",
        raw,
        flags=re.IGNORECASE,
    )

    if match_p:
        return match_p.group(1).upper()

    # Código numérico largo.
    # Solo lo tomamos si tiene mínimo 6 dígitos consecutivos.
    match_num = re.search(r"\b([0-9]{6,})\b", raw)

    if match_num:
        return match_num.group(1)

    return None


def _is_clean_greeting(message: str) -> bool:
    """
    Detecta saludos puros.

    Debe ser True para:
    - hola
    - hola buenas
    - buenas tardes

    Debe ser False para:
    - hola necesito un sensor
    - buenas, me regalas precio del variador
    """
    msg = _normalize(message)

    if not msg:
        return False

    exact_greetings = {
        "hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hola buenas",
        "hola buenos dias",
        "hola buenas tardes",
        "hola buenas noches",
        "hey",
        "que tal",
    }

    if msg in exact_greetings:
        return True

    tokens = set(re.findall(r"[a-zñ]+", msg))

    greeting_tokens = {
        "hola",
        "buenas",
        "buenos",
        "dias",
        "tardes",
        "noches",
        "hey",
        "que",
        "tal",
        "saludos",
    }

    return bool(tokens) and tokens.issubset(greeting_tokens)


# =========================================================
# DETECCIÓN PRINCIPAL
# =========================================================

def detect_intent(message: str) -> dict:
    """
    Detecta la intención principal del usuario.

    Retorna:
    {
        "intent": "...",
        "code": "P382280" | None
    }
    """

    if not message:
        return {"intent": "desconocido"}

    msg = _normalize(message)

    # =====================================================
    # CÓDIGO DE PRODUCTO DENTRO DE FRASE
    # =====================================================

    exact_code = extract_exact_product_code(message)

    if exact_code:
        return {
            "intent": "codigo_producto",
            "code": exact_code,
        }

    # =====================================================
    # SALUDOS PUROS
    # =====================================================

    if _is_clean_greeting(message):
        return {"intent": "saludo"}

    # =====================================================
    # INTENCIÓN COMERCIAL
    # =====================================================

    palabras_comerciales = [
        "cotizacion",
        "cotizar",
        "cotizame",
        "cotizame",
        "precio",
        "precios",
        "cuanto vale",
        "cuanto cuesta",
        "me regalas",
        "me das",
        "regalame",
        "comprar",
        "compra",
        "descuento",
        "disponibilidad",
        "stock",
        "entrega",
        "tiempo de entrega",
        "necesito comprar",
    ]

    has_commercial = any(p in msg for p in palabras_comerciales)

    # =====================================================
    # INTENCIÓN DE PRODUCTO
    # =====================================================

    palabras_producto = [
        "producto",
        "sensor",
        "sensores",
        "valvula",
        "valvulas",
        "electrovalvula",
        "motor",
        "motores",
        "motorreductor",
        "transmisor",
        "presion",
        "temperatura",
        "caudal",
        "nivel",
        "switch",
        "encoder",
        "variador",
        "variadores",
        "drive",
        "vfd",
        "plc",
        "hmi",
        "torquimetro",
        "herramienta",
        "bomba",
        "manometro",
        "breaker",
        "contactor",
        "rele",
        "fuente",
    ]

    has_product = any(p in msg for p in palabras_producto)

    if has_product:
        return {
            "intent": "producto",
            "commercial_signal": has_commercial,
        }

    if has_commercial:
        return {"intent": "comercial"}

    # =====================================================
    # DETECCIÓN DE REFERENCIA ALFANUMÉRICA GENERAL
    # =====================================================
    # Cubre referencias industriales tipo:
    # - 1LE21212BC214AA3
    # - ATV320U22M2C
    # - 6ES7214-1AG40-0XB0
    #
    # NO debe detectar unidades técnicas como:
    # - 200nm
    # - 220v
    # - 3hp
    # - 10bar
    # =====================================================

    technical_unit_pattern = (
        r"^\d+(?:[\.,]\d+)?\s*"
        r"(nm|n\.m|n-m|v|vac|vca|vdc|vcc|hp|kw|kva|va|bar|psi|rpm|mm|cm|m|kg|lb|ton)$"
    )

    if re.fullmatch(technical_unit_pattern, msg):
        return {"intent": "producto"}

    codigo_pattern = r"\b(?=.*[a-zA-Z])(?=.*\d)[a-zA-Z0-9\-\/]{6,}\b"
    match_ref = re.search(codigo_pattern, message.strip())

    if match_ref:
        candidate = match_ref.group(0)
        candidate_n = _normalize(candidate)

        if not re.fullmatch(technical_unit_pattern, candidate_n):
            return {
                "intent": "codigo_producto",
                "code": candidate,
            }

    # =====================================================
    # FALLBACK
    # =====================================================

    return {"intent": "general"}