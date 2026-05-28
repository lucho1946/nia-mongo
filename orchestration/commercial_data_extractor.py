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

    Nota:
    Por ahora usamos capitalize por palabra. Esto convierte ABC -> Abc.
    Más adelante podemos mejorar preservación de siglas.
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


def _cut_at_stop_words(value: str) -> str:
    """
    Corta un valor cuando empiezan otros datos o frases que no pertenecen
    al campo capturado.

    Sirve para:
    - nombres
    - empresas
    - presupuestos
    """
    value = clean_value(value)

    if not value:
        return ""

    parts = re.split(
        r"\s+(?:"
        r"y\s+mi\s+correo|"
        r"mi\s+correo|"
        r"correo|"
        r"email|"
        r"e-mail|"
        r"mail|"
        r"mi\s+telefono|"
        r"mi\s+tel[eé]fono|"
        r"telefono|"
        r"tel[eé]fono|"
        r"celular|"
        r"mi\s+celular|"
        r"mi\s+numero|"
        r"mi\s+n[uú]mero|"
        r"numero|"
        r"n[uú]mero|"
        r"cantidad|"
        r"presupuesto|"
        r"para\s+cotizar|"
        r"para\s+la\s+cotizaci[oó]n|"
        r"para\s+continuar|"
        r"gracias"
        r")\b",
        value,
        flags=re.IGNORECASE,
    )

    return clean_value(parts[0] if parts else value)


def _looks_like_company(value: str) -> bool:
    """
    Heurística suave para validar que un texto pueda ser empresa.

    No exige que tenga SAS/LTDA, porque muchas empresas reales se escriben como:
    - Industrias ABC
    - Taller El Norte
    - Ferretería Mundial
    - Constructora Los Andes
    """
    value = clean_value(value)

    if not value:
        return False

    words = value.split()

    if len(words) > 8:
        return False

    # Evita capturar textos demasiado genéricos.
    normalized = normalize_text(value)

    blocked = {
        "si",
        "no",
        "ok",
        "listo",
        "gracias",
        "empresa",
        "la empresa",
        "mi empresa",
        "correo",
        "telefono",
        "cotizacion",
        "producto",
    }

    if normalized in blocked:
        return False

    return True


def _extract_company_after_marker(raw: str) -> str:
    """
    Extrae empresa usando marcadores explícitos.

    Soporta frases naturales como:
    - "La empresa es Industrias ABC"
    - "Mi empresa es Industrias ABC"
    - "La empresa se llama Industrias ABC"
    - "Se llama Industrias ABC" cuando el mensaje menciona empresa
    - "Empresa: Industrias ABC"
    - "De la empresa Industrias ABC"
    - "Trabajo en Industrias ABC"
    - "Laboro en Industrias ABC"
    """
    raw = str(raw or "")

    # Marcadores muy explícitos.
    patterns = [
        r"\bempresa\s*[:\-]?\s*(?:es|se llama|llamada|nombre)?\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bmi empresa\s*(?:es|se llama|llamada)?\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bla empresa\s*(?:es|se llama|llamada)?\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bde la empresa\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bpara la empresa\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\btrabajo en\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\blaboro en\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bsoy de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bvengo de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\brepresento a\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\brepresento la empresa\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
        r"\bsomos\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if not match:
            continue

        company = _cut_at_stop_words(match.group(1))

        # Caso especial:
        # "Ya te dije la empresa. Se llama Industria ABC"
        # El primer patrón puede capturar vacío o texto raro; lo limpiamos.
        company = re.sub(
            r"^(?:es|se llama|llamada)\s+",
            "",
            company,
            flags=re.IGNORECASE,
        )

        company = clean_value(company)

        if _looks_like_company(company):
            return title_safe(company)

    # Marcador "se llama X" solo si el mensaje menciona empresa.
    normalized = normalize_text(raw)

    if "empresa" in normalized or "compania" in normalized or "compañia" in normalized:
        match = re.search(
            r"\bse llama\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
            raw,
            flags=re.IGNORECASE,
        )

        if match:
            company = _cut_at_stop_words(match.group(1))
            company = clean_value(company)

            if _looks_like_company(company):
                return title_safe(company)

    return ""


def _extract_company_from_name_phrase(raw: str) -> str:
    """
    Extrae empresa en frases donde el usuario se presenta y agrega "de X".

    Soporta:
    - "Mi nombre es Luis Diaz de Industrias ABC y mi correo es..."
    - "Me llamo Luis Diaz de Industrias ABC"
    - "Soy Carlos de Industrias ABC"
    - "Hablas con Laura de Industrias Norte"
    - "Soy Luis, de Industrias ABC"
    """
    raw = str(raw or "")

    patterns = [
        # Mi nombre es Luis Diaz de Industrias ABC...
        r"\bmi nombre es\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Me llamo Luis Diaz de Industrias ABC...
        r"\bme llamo\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Soy Carlos de Industrias ABC...
        r"\bsoy\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Hablas con Laura de Industrias Norte...
        r"\bhablas con\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Te habla Laura de Industrias Norte...
        r"\bte habla\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Soy Luis, de Industrias ABC
        r"\bsoy\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?,\s*de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Mi nombre es Luis, de Industrias ABC
        r"\bmi nombre es\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?,\s*de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",

        # Me llamo Luis, de Industrias ABC
        r"\bme llamo\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?,\s*de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .&_\-]{2,100})",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if not match:
            continue

        company = _cut_at_stop_words(match.group(1))
        company = clean_value(company)

        if _looks_like_company(company):
            return title_safe(company)

    return ""


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
        r"\b(?:cantidad|cant\.?|serian|serían)\s*(?:de\s*)?(\d{1,4})\s*(?:und|unid|unidad|unidades|piezas|pz|pcs)?\b",
        r"\b(?:necesito|requiero|quiero)\s+(\d{1,4})\s*(?:und|unid|unidad|unidades|piezas|pz|pcs)\b",
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

    Casos soportados:
    - "Me llamo Andrea"
    - "Mi nombre es Carlos"
    - "Mi nombre es Luis Diaz de Industrias ABC"
    - "Soy Carlos de Industrias ABC"
    - "Soy Carlos, mi correo es..."
    - "Nombre: Carlos"

    Regla importante:
    Si el usuario dice "Soy Carlos de Industrias ABC",
    el nombre debe quedar "Carlos", no "Carlos de Industrias ABC".
    """
    raw = str(message or "")

    patterns = [
        # Mi nombre es Luis Diaz de Industrias ABC...
        r"\bmi nombre es\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?)(?=\s+de\s+|,|\.|$|\s+y\s+mi\s+|\s+mi\s+|\s+correo\s+|\s+tel[eé]fono\s+|\s+celular\s+|\s+empresa\s+)",

        # Me llamo Andrea...
        r"\bme llamo\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?)(?=\s+de\s+|,|\.|$|\s+y\s+mi\s+|\s+mi\s+|\s+correo\s+|\s+tel[eé]fono\s+|\s+celular\s+|\s+empresa\s+)",

        # Soy Carlos de Industrias ABC...
        r"\bsoy\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?)(?=\s+de\s+|,|\.|$|\s+y\s+mi\s+|\s+mi\s+|\s+correo\s+|\s+tel[eé]fono\s+|\s+celular\s+|\s+empresa\s+)",

        # Hablas con Laura...
        r"\bhablas con\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?)(?=\s+de\s+|,|\.|$|\s+y\s+mi\s+|\s+mi\s+|\s+correo\s+|\s+tel[eé]fono\s+|\s+celular\s+|\s+empresa\s+)",

        # Te habla Laura...
        r"\bte habla\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?)(?=\s+de\s+|,|\.|$|\s+y\s+mi\s+|\s+mi\s+|\s+correo\s+|\s+tel[eé]fono\s+|\s+celular\s+|\s+empresa\s+)",

        # Nombre: Carlos
        r"\bnombre\s*[:\-]?\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,60}?)(?=,|\.|$|\s+empresa\s+|\s+correo\s+|\s+tel[eé]fono\s+|\s+celular\s+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)

        if match:
            name = clean_value(match.group(1))

            # Limpieza defensiva por si entra texto adicional.
            name = re.split(
                r"\s+(?:de la empresa|de|empresa|mi correo|correo|telefono|teléfono|celular|mi numero|mi número)\b",
                name,
                flags=re.IGNORECASE,
            )[0]

            name = clean_value(name)

            # Evita guardar frases largas como nombre.
            if name and len(name.split()) <= 5:
                return title_safe(name)

    return ""


def extract_company(message: str) -> str:
    """
    Extrae empresa cuando viene con señales claras.

    Casos soportados:
    - "Soy Carlos de Industrias ABC"
    - "Mi nombre es Luis Diaz de Industrias ABC y mi correo es..."
    - "Me llamo Laura de Industrias Norte"
    - "Trabajo en Industrias ABC"
    - "Laboro en Industrias ABC"
    - "Empresa: Industrias ABC"
    - "Mi empresa es Industrias ABC"
    - "La empresa es Industrias ABC"
    - "La empresa se llama Industrias ABC"
    - "Ya te dije la empresa. Se llama Industria ABC"
    - "Represento a Industrias ABC"
    - "Somos Industrias ABC"

    Regla:
    La empresa se corta antes de correo, teléfono u otros datos.
    """
    raw = str(message or "")

    # 1. Primero intentamos con marcadores explícitos de empresa.
    company = _extract_company_after_marker(raw)

    if company:
        return company

    # 2. Luego intentamos extraer empresa en frases de presentación personal.
    company = _extract_company_from_name_phrase(raw)

    if company:
        return company

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