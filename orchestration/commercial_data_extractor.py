# ============================================================
# orchestration/commercial_data_extractor.py
# ============================================================
# RESPONSABILIDAD:
# Extraer datos comerciales desde mensajes naturales del cliente.
#
# Este módulo convierte texto humano en datos estructurados para:
# - cotización
# - proforma
# - seguimiento comercial
#
# Alineación NIA OS / Don Andrés:
# - No pedir datos repetidos.
# - Capturar datos comerciales útiles.
# - Mantener continuidad del hilo comercial.
# - No inventar información.
#
# Este módulo NO busca productos.
# Este módulo NO llama OpenAI.
# Este módulo NO decide cotización oficial.
# Solo extrae señales claras del mensaje del usuario.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List


COMMERCIAL_DATA_KEYS = [
    "nombre_cliente",
    "empresa",
    "correo",
    "telefono",
    "cantidad",
    "presupuesto_aproximado",
    "fecha_estimada_compra",
]


# ============================================================
# UTILIDADES
# ============================================================

def normalize_text(value: Any) -> str:
    """
    Normaliza texto para detección:
    - minúsculas
    - sin acentos
    - espacios limpios
    """
    text = "" if value is None else str(value)
    text = text.lower().strip()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text)


def clean_value(value: Any) -> str:
    """
    Limpia valores extraídos sin cambiar demasiado el contenido original.
    """
    text = "" if value is None else str(value)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" .,:;|-")
    return text


def title_safe(value: str) -> str:
    """
    Da formato legible sin forzar demasiado.
    """
    value = clean_value(value)

    if not value:
        return ""

    return " ".join(
        part.capitalize()
        for part in value.split()
    )


def has_any_commercial_data(data: Dict[str, Any]) -> bool:
    """
    Indica si se extrajo al menos un dato comercial útil.
    """
    return any(
        data.get(key) not in [None, "", [], {}]
        for key in COMMERCIAL_DATA_KEYS
    )


# ============================================================
# EXTRACTORES INDIVIDUALES
# ============================================================

def extract_email(message: str) -> str:
    """
    Extrae correo electrónico.
    """
    match = re.search(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        message or "",
    )

    if not match:
        return ""

    return clean_value(match.group(0)).lower()


def extract_phone(message: str) -> str:
    """
    Extrae teléfono probable.

    Reglas:
    - Acepta números colombianos tipo 3001234567.
    - Acepta +57 300 123 4567.
    - Evita confundir códigos de producto cortos, voltajes o unidades técnicas.
    """
    raw = str(message or "")

    candidates = re.findall(
        r"(?:\+?\d[\d\s().-]{6,}\d)",
        raw,
    )

    for candidate in candidates:
        normalized = re.sub(r"\D", "", candidate)

        # Remueve indicativo Colombia si viene incluido.
        if normalized.startswith("57") and len(normalized) >= 12:
            normalized = normalized[2:]

        # Teléfono fijo/celular razonable.
        if 7 <= len(normalized) <= 10:
            # Evita confundir valores técnicos muy comunes.
            if normalized in {"110", "220", "440", "380", "24"}:
                continue

            return normalized

    return ""


def extract_quantity(message: str) -> str:
    """
    Extrae cantidad solo cuando hay palabras comerciales cercanas.
    Evita confundir códigos de producto.
    """
    text = normalize_text(message)

    patterns = [
        r"\b(?:cantidad|cant\.?|necesito|requiero|quiero|serian|serían)\s*(?:de\s*)?(\d{1,4})\s*(?:und|unid|unidad|unidades|piezas|pz|pcs)?\b",
        r"\b(\d{1,4})\s*(?:und|unid|unidad|unidades|piezas|pz|pcs)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(1)

    return ""


def extract_budget(message: str) -> str:
    """
    Extrae presupuesto aproximado.
    """
    raw = str(message or "")
    text = normalize_text(raw)

    money_match = re.search(
        r"(\$?\s*\d{1,3}(?:[.,]\d{3})+(?:\s*(?:cop|pesos)?)?)",
        raw,
        flags=re.IGNORECASE,
    )

    if money_match:
        return clean_value(money_match.group(1))

    million_match = re.search(
        r"\b(?:presupuesto|tengo|contamos con|aproximadamente|aprox)\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*(millones|millon|millón)\b",
        text,
    )

    if million_match:
        return f"{million_match.group(1)} {million_match.group(2)}"

    budget_match = re.search(
        r"\bpresupuesto\s*(?:aproximado|aprox)?\s*(?:de|es)?\s*([a-z0-9$.,\s]+)",
        text,
    )

    if budget_match:
        value = clean_value(budget_match.group(1))

        if value:
            return value

    return ""


def extract_purchase_date(message: str) -> str:
    """
    Extrae fecha estimada de compra en forma textual.
    """
    text = normalize_text(message)

    direct_patterns = [
        "hoy",
        "mañana",
        "manana",
        "esta semana",
        "la otra semana",
        "proxima semana",
        "próxima semana",
        "este mes",
        "el otro mes",
        "proximo mes",
        "próximo mes",
        "urgente",
        "lo antes posible",
    ]

    for value in direct_patterns:
        if normalize_text(value) in text:
            return value

    in_days = re.search(r"\ben\s+(\d{1,3})\s+dias\b", text)

    if in_days:
        return f"en {in_days.group(1)} días"

    date_like = re.search(
        r"\b(?:para|el)\s+(\d{1,2}\s+de\s+[a-zñ]+)\b",
        text,
    )

    if date_like:
        return date_like.group(1)

    return ""


def extract_name(message: str) -> str:
    """
    Extrae nombre del cliente cuando viene explícito.
    """
    raw = str(message or "")

    patterns = [
        r"\bmi nombre es\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,50})",
        r"\bme llamo\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,50})",
        r"\bsoy\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})(?:\s+de\s+|,|\.|$)",
        r"\bnombre\s*[:\-]?\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,50})",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if match:
            name = clean_value(match.group(1))

            # Evita tomar frases comerciales completas como nombre.
            name = re.split(
                r"\s+(?:mi correo|correo|telefono|teléfono|celular|empresa)\b",
                name,
                flags=re.IGNORECASE,
            )[0]

            name = clean_value(name)

            if name:
                return title_safe(name)

    return ""


def extract_company(message: str) -> str:
    """
    Extrae empresa cuando viene con señales claras.
    """
    raw = str(message or "")

    patterns = [
        r"\bempresa\s*[:\-]?\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_-]{2,80})",
        r"\bde la empresa\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_-]{2,80})",
        r"\btrabajo en\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_-]{2,80})",
        r"\bsoy\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40}\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_-]{2,80})",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if match:
            company = clean_value(match.group(1))

            # Corta cuando empiezan otros datos.
            company = re.split(
                r"\s+(?:mi correo|correo|telefono|teléfono|celular|mi numero|mi número)\b",
                company,
                flags=re.IGNORECASE,
            )[0]

            company = clean_value(company)

            if company:
                return title_safe(company)

    return ""


# ============================================================
# EXTRACTOR PRINCIPAL
# ============================================================

def extract_commercial_data(message: str) -> Dict[str, Any]:
    """
    Extrae datos comerciales desde un mensaje.

    Retorna siempre todas las claves con None o valor.
    """
    data = {
        "nombre_cliente": None,
        "empresa": None,
        "correo": None,
        "telefono": None,
        "cantidad": None,
        "presupuesto_aproximado": None,
        "fecha_estimada_compra": None,
    }

    email = extract_email(message)
    phone = extract_phone(message)
    quantity = extract_quantity(message)
    budget = extract_budget(message)
    purchase_date = extract_purchase_date(message)
    name = extract_name(message)
    company = extract_company(message)

    if name:
        data["nombre_cliente"] = name

    if company:
        data["empresa"] = company

    if email:
        data["correo"] = email

    if phone:
        data["telefono"] = phone

    if quantity:
        data["cantidad"] = quantity

    if budget:
        data["presupuesto_aproximado"] = budget

    if purchase_date:
        data["fecha_estimada_compra"] = purchase_date

    return data


def merge_commercial_data(
    current: Dict[str, Any],
    incoming: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Combina datos comerciales sin sobrescribir con vacíos.
    """
    merged = dict(current or {})

    for key in COMMERCIAL_DATA_KEYS:
        value = incoming.get(key)

        if value not in [None, "", [], {}]:
            merged[key] = value

        elif key not in merged:
            merged[key] = None

    return merged


# ============================================================
# FALTANTES PARA COTIZACIÓN
# ============================================================

def get_missing_quote_fields(data: Dict[str, Any]) -> List[str]:
    """
    Define datos mínimos para avanzar con una solicitud comercial.

    Regla inicial:
    - nombre_cliente
    - empresa
    - al menos un medio de contacto: correo o teléfono
    """
    data = data or {}
    missing: List[str] = []

    if not data.get("nombre_cliente"):
        missing.append("nombre")

    if not data.get("empresa"):
        missing.append("empresa")

    if not data.get("correo") and not data.get("telefono"):
        missing.append("correo o teléfono")

    return missing


def get_received_quote_fields(data: Dict[str, Any]) -> List[str]:
    """
    Lista campos útiles ya recibidos.
    """
    data = data or {}
    received: List[str] = []

    if data.get("nombre_cliente"):
        received.append("nombre")

    if data.get("empresa"):
        received.append("empresa")

    if data.get("correo"):
        received.append("correo")

    if data.get("telefono"):
        received.append("teléfono")

    if data.get("cantidad"):
        received.append("cantidad")

    if data.get("presupuesto_aproximado"):
        received.append("presupuesto aproximado")

    if data.get("fecha_estimada_compra"):
        received.append("fecha estimada de compra")

    return received


def build_missing_quote_fields_text(missing: List[str]) -> str:
    """
    Convierte faltantes en texto natural.
    """
    missing = [item for item in missing if item]

    if not missing:
        return ""

    if len(missing) == 1:
        return missing[0]

    if len(missing) == 2:
        return f"{missing[0]} y {missing[1]}"

    return ", ".join(missing[:-1]) + f" y {missing[-1]}"


def build_received_fields_text(received: List[str]) -> str:
    """
    Convierte campos recibidos en texto natural.
    """
    received = [item for item in received if item]

    if not received:
        return ""

    if len(received) == 1:
        return received[0]

    if len(received) == 2:
        return f"{received[0]} y {received[1]}"

    return ", ".join(received[:-1]) + f" y {received[-1]}"


def build_commercial_data_response(data: Dict[str, Any]) -> str:
    """
    Construye respuesta después de recibir datos comerciales.
    """
    missing = get_missing_quote_fields(data)
    received = get_received_quote_fields(data)

    name = data.get("nombre_cliente")
    greeting = f"Gracias, {name}." if name else "Gracias."

    received_text = build_received_fields_text(received)

    if missing:
        missing_text = build_missing_quote_fields_text(missing)

        if received_text:
            return (
                f"{greeting} Ya tengo {received_text}. "
                f"Para continuar con la cotización, ¿me confirmas {missing_text}?"
            )

        return (
            f"{greeting} Para continuar con la cotización, "
            f"¿me confirmas {missing_text}?"
        )

    if received_text:
        return (
            f"{greeting} Ya tengo {received_text}. "
            "Con estos datos puedo dejar la solicitud de cotización en proceso."
        )

    return (
        "Gracias. Con estos datos puedo dejar la solicitud de cotización en proceso."
    )