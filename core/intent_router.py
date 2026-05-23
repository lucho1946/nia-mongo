# =========================================================
# INTENT ROUTER — NIA OS
# =========================================================

import re


def detect_intent(message: str) -> dict:
    """
    Detecta la intención principal del usuario.
    """

    if not message:
        return {"intent": "desconocido"}

    msg = message.lower().strip()

    # =====================================================
    # SALUDOS
    # =====================================================

    saludos = [
        "hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hey",
        "que tal"
    ]

    if any(s in msg for s in saludos):
        return {"intent": "saludo"}

    # =====================================================
    # INTENCIÓN COMERCIAL
    # =====================================================

    palabras_comerciales = [
        "cotizacion",
        "cotización",
        "precio",
        "comprar",
        "descuento",
        "disponibilidad",
        "entrega"
    ]

    if any(p in msg for p in palabras_comerciales):
        return {"intent": "comercial"}

    # =====================================================
    # INTENCIÓN DE PRODUCTO
    # =====================================================

    palabras_producto = [
        "sensor",
        "valvula",
        "válvula",
        "motor",
        "transmisor",
        "presion",
        "presión",
        "temperatura",
        "caudal",
        "nivel",
        "switch",
        "encoder",
        "variador"
    ]

    if any(p in msg for p in palabras_producto):
        return {"intent": "producto"}

    # =====================================================
    # DETECCIÓN DE CÓDIGO INDUSTRIAL
    # =====================================================

    codigo_pattern = r'^(?=.*[a-zA-Z])(?=.*\d)[a-zA-Z0-9\-]{5,}$'

    if re.match(codigo_pattern, message.strip()):
        return {"intent": "codigo_producto"}

    # =====================================================
    # FALLBACK
    # =====================================================

    return {"intent": "general"}