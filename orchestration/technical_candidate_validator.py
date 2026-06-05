# ============================================================
# orchestration/technical_candidate_validator.py
# ============================================================
# RESPONSABILIDAD:
# Validar si un candidato real del catálogo contradice
# especificaciones técnicas explícitas dadas por el cliente.
#
# Este módulo NO busca productos.
# Este módulo NO llama OpenAI.
# Este módulo NO recomienda productos.
# Este módulo NO usa familias manuales.
# Este módulo NO contiene lógica por producto específico.
#
# Objetivo:
# Evitar recomendaciones incompatibles cuando el cliente ya dio
# una especificación técnica clara.
#
# Ejemplos genéricos:
# - Cliente pide 100 m y producto dice 30 m  -> incompatible.
# - Cliente pide 10 bar y producto dice 4 bar -> incompatible.
# - Cliente pide 200 Nm y producto dice 50 Nm -> incompatible.
#
# La validación solo bloquea cuando hay evidencia numérica clara
# tanto en el contexto del cliente como en el producto.
# Si no hay evidencia suficiente, no bloquea.
# ============================================================

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


VALIDATOR_VERSION = "technical_candidate_validator_v1"


# ============================================================
# UTILIDADES
# ============================================================

def _safe_text(value: Any) -> str:
    """
    Convierte cualquier valor a texto seguro.
    """
    if value in [None, "", [], {}]:
        return ""

    try:
        return str(value).strip()
    except Exception:
        return ""


def _normalize(text: Any) -> str:
    """
    Normaliza texto para comparaciones generales.
    """
    text = _safe_text(text).lower()

    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    return re.sub(r"\s+", " ", text).strip()


def _parse_float(value: str) -> Optional[float]:
    """
    Convierte un número textual a float.
    Soporta coma decimal.
    """
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _collect_product_text(product: Dict[str, Any]) -> str:
    """
    Construye texto bruto desde todos los campos útiles del producto.

    Importante:
    - No depende de una estructura única del catálogo.
    - Lee campos planos y también estructuras anidadas.
    - Esto permite detectar especificaciones como:
      "100m", "100 metros", "Longitud: 100 metros",
      aunque vengan en características, atributos o texto enriquecido.
    """
    if not isinstance(product, dict):
        return ""

    parts: List[str] = []

    priority_fields = [
        "CODIGO",
        "REFERENCIA",
        "REF_ALTERNATIVA",
        "NOMBRE_PRODUCTO",
        "DESCRIPCION_CORTA_PRE",
        "DESCRIPCION_LARGA_PRE",
        "MARCA_LET",
        "NIVEL_0",
        "NIVEL_1",
        "NIVEL_2",
        "NIVEL_3",
        "NIVEL_4",
        "APLICACIONES",
        "CARACTERISTICAS",
        "CARACTERISTICAS_TECNICAS",
        "ATRIBUTOS",
        "ATRIBUTOS_TECNICOS",
        "texto_busqueda",
        "codigo",
        "referencia",
        "nombre",
        "descripcion",
        "marca",
        "nivel_0",
        "nivel_1",
        "nivel_2",
        "nivel_3",
        "nivel_4",
        "caracteristicas",
        "aplicaciones",
    ]

    def append_value(value: Any) -> None:
        """
        Agrega valores de forma recursiva.
        """
        if value in [None, "", [], {}]:
            return

        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if nested_key not in [None, ""]:
                    parts.append(str(nested_key))
                append_value(nested_value)
            return

        if isinstance(value, list):
            for item in value:
                append_value(item)
            return

        parts.append(str(value))

    # Primero campos prioritarios.
    for field in priority_fields:
        if field in product:
            append_value(product.get(field))

    # Luego todos los demás campos del producto.
    # Esto cubre variaciones del catálogo sin quemar nombres de columnas.
    for key, value in product.items():
        if key in priority_fields:
            continue

        parts.append(str(key))
        append_value(value)

    # Limpieza básica de duplicados conservando orden.
    clean_parts: List[str] = []
    seen = set()

    for part in parts:
        clean = str(part or "").strip()

        if not clean:
            continue

        fingerprint = clean.lower()

        if fingerprint in seen:
            continue

        seen.add(fingerprint)
        clean_parts.append(clean)

    return " ".join(clean_parts)


def _collect_context_text(context: Dict[str, Any]) -> str:
    """
    Construye texto desde los campos técnicos explícitos del contexto.
    """
    if not isinstance(context, dict):
        return ""

    keys = [
        "technical_clarification",
        "medida",
        "rango",
        "presion",
        "temperatura",
        "caudal",
        "nivel",
        "potencia",
        "voltaje",
        "corriente",
        "diametro",
        "conexion",
        "salida",
        "comunicacion",
        "material",
        "aplicacion",
    ]

    parts = []

    for key in keys:
        value = context.get(key)

        if value not in [None, "", [], {}]:
            parts.append(str(value))

    return " ".join(parts)


# ============================================================
# EXTRACCIÓN NUMÉRICA GENÉRICA
# ============================================================

def _extract_length_meters(text: str) -> List[float]:
    """
    Extrae longitudes/rangos en metros.

    Nota:
    - Acepta 30m, 30 m, 30 metros.
    - No acepta 1025M con M mayúscula para evitar confundir modelos.
    """
    raw = _safe_text(text)
    values: List[float] = []

    patterns = [
        (r"(\d+(?:[\.,]\d+)?)\s*(metros?|mts?)\b", 1.0),
        (r"(\d+(?:[\.,]\d+)?)\s*m\b", 1.0),
        (r"(\d+(?:[\.,]\d+)?)\s*cm\b", 0.01),
        (r"(\d+(?:[\.,]\d+)?)\s*mm\b", 0.001),
        (r"(\d+(?:[\.,]\d+)?)\s*(ft|pies|pie)\b", 0.3048),
    ]

    for pattern, factor in patterns:
        for match in re.finditer(pattern, raw):
            value = _parse_float(match.group(1))

            if value is not None:
                values.append(value * factor)

    return values


def _extract_pressure_bar(text: str) -> List[float]:
    """
    Extrae presión y convierte a bar.
    """
    raw = _normalize(text)
    values: List[float] = []

    patterns = [
        (r"(\d+(?:[\.,]\d+)?)\s*bar\b", 1.0),
        (r"(\d+(?:[\.,]\d+)?)\s*psi\b", 0.0689476),
        (r"(\d+(?:[\.,]\d+)?)\s*kpa\b", 0.01),
        (r"(\d+(?:[\.,]\d+)?)\s*mpa\b", 10.0),
        (r"(\d+(?:[\.,]\d+)?)\s*pa\b", 0.00001),
    ]

    for pattern, factor in patterns:
        for match in re.finditer(pattern, raw):
            value = _parse_float(match.group(1))

            if value is not None:
                values.append(value * factor)

    return values


def _extract_torque_nm(text: str) -> List[float]:
    """
    Extrae torque y convierte a Nm.
    """
    raw = _normalize(text)
    values: List[float] = []

    patterns = [
        (r"(\d+(?:[\.,]\d+)?)\s*(nm|n\.m|n-m|newton\s*metro|newton\s*metros)\b", 1.0),
        (r"(\d+(?:[\.,]\d+)?)\s*(ft[\s-]*lb|lb[\s-]*ft|pies[\s-]*libras|pie[\s-]*libra)\b", 1.35582),
    ]

    for pattern, factor in patterns:
        for match in re.finditer(pattern, raw):
            value = _parse_float(match.group(1))

            if value is not None:
                values.append(value * factor)

    return values


def _extract_power_kw(text: str) -> List[float]:
    """
    Extrae potencia y convierte a kW.
    """
    raw = _normalize(text)
    values: List[float] = []

    patterns = [
        (r"(\d+(?:[\.,]\d+)?)\s*kw\b", 1.0),
        (r"(\d+(?:[\.,]\d+)?)\s*w\b", 0.001),
        (r"(\d+(?:[\.,]\d+)?)\s*hp\b", 0.7457),
    ]

    for pattern, factor in patterns:
        for match in re.finditer(pattern, raw):
            value = _parse_float(match.group(1))

            if value is not None:
                values.append(value * factor)

    return values


def _extract_voltage_v(text: str) -> List[float]:
    """
    Extrae voltaje.
    """
    raw = _normalize(text)
    values: List[float] = []

    pattern = r"(\d+(?:[\.,]\d+)?)\s*(v|vac|vca|vdc|vcc)\b"

    for match in re.finditer(pattern, raw):
        value = _parse_float(match.group(1))

        if value is not None:
            values.append(value)

    return values


def _extract_current_a(text: str) -> List[float]:
    """
    Extrae corriente.
    """
    raw = _normalize(text)
    values: List[float] = []

    pattern = r"(\d+(?:[\.,]\d+)?)\s*(a|amp|amperios?)\b"

    for match in re.finditer(pattern, raw):
        value = _parse_float(match.group(1))

        if value is not None:
            values.append(value)

    return values


def _dedupe_numbers(values: List[float]) -> List[float]:
    """
    Elimina duplicados numéricos conservando orden.
    """
    clean: List[float] = []

    for value in values:
        try:
            number = round(float(value), 6)
        except (TypeError, ValueError):
            continue

        if number not in clean:
            clean.append(number)

    return clean


def _extract_numeric_specs(text: str) -> Dict[str, List[float]]:
    """
    Extrae especificaciones numéricas conocidas.

    No interpreta producto.
    Solo extrae unidades técnicas explícitas.
    """
    return {
        "length_m": _dedupe_numbers(_extract_length_meters(text)),
        "pressure_bar": _dedupe_numbers(_extract_pressure_bar(text)),
        "torque_nm": _dedupe_numbers(_extract_torque_nm(text)),
        "power_kw": _dedupe_numbers(_extract_power_kw(text)),
        "voltage_v": _dedupe_numbers(_extract_voltage_v(text)),
        "current_a": _dedupe_numbers(_extract_current_a(text)),
    }


# ============================================================
# COMPARACIÓN GENÉRICA
# ============================================================

def _candidate_covers_required(
    required_values: List[float],
    candidate_values: List[float],
    *,
    tolerance_ratio: float = 0.95,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Valida si algún valor del candidato cubre el valor requerido.

    Para capacidades/rangos:
    - Si el cliente pide 100 m, producto 30 m no cubre.
    - Si el cliente pide 100 m, producto 100 m o 120 m cubre.

    Usamos tolerancia mínima para evitar bloquear por redondeos pequeños.
    """
    if not required_values:
        return True, {
            "reason": "no_required_values",
        }

    if not candidate_values:
        return True, {
            "reason": "no_candidate_values",
        }

    required_max = max(required_values)
    candidate_max = max(candidate_values)

    compatible = candidate_max >= (required_max * tolerance_ratio)

    return compatible, {
        "required_max": required_max,
        "candidate_max": candidate_max,
        "tolerance_ratio": tolerance_ratio,
    }


def validate_candidate_against_technical_requirements(
    context: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Valida un candidato contra requerimientos técnicos explícitos.

    Retorna compatible=False solo cuando hay contradicción numérica clara.
    Si no hay suficiente evidencia, no bloquea.
    """
    context_text = _collect_context_text(context)
    product_text = _collect_product_text(candidate)

    requested_specs = _extract_numeric_specs(context_text)
    candidate_specs = _extract_numeric_specs(product_text)

    checked: List[Dict[str, Any]] = []
    blocking: List[Dict[str, Any]] = []

    # Para estas dimensiones, el producto debe cubrir al menos
    # el valor solicitado.
    comparable_dimensions = [
        "length_m",
        "pressure_bar",
        "torque_nm",
        "power_kw",
        "current_a",
    ]

    for dimension in comparable_dimensions:
        required_values = requested_specs.get(dimension, [])
        product_values = candidate_specs.get(dimension, [])

        compatible, evidence = _candidate_covers_required(
            required_values,
            product_values,
        )

        item = {
            "dimension": dimension,
            "compatible": compatible,
            "required_values": required_values,
            "candidate_values": product_values,
            "evidence": evidence,
        }

        checked.append(item)

        if required_values and product_values and not compatible:
            blocking.append(
                {
                    **item,
                    "reason": "candidate_value_below_required",
                }
            )

    # Voltaje se maneja con cuidado: si hay valores en ambos lados,
    # debe existir un valor cercano. No bloqueamos cuando falta evidencia.
    required_voltage = requested_specs.get("voltage_v", [])
    candidate_voltage = candidate_specs.get("voltage_v", [])

    if required_voltage and candidate_voltage:
        voltage_ok = any(
            abs(candidate - required) <= max(5.0, required * 0.05)
            for required in required_voltage
            for candidate in candidate_voltage
        )

        voltage_item = {
            "dimension": "voltage_v",
            "compatible": voltage_ok,
            "required_values": required_voltage,
            "candidate_values": candidate_voltage,
            "reason": "voltage_match" if voltage_ok else "voltage_mismatch",
        }

        checked.append(voltage_item)

        if not voltage_ok:
            blocking.append(voltage_item)

    compatible = len(blocking) == 0

    return {
        "ok": True,
        "version": VALIDATOR_VERSION,
        "compatible": compatible,
        "reason": "technical_requirements_compatible" if compatible else "technical_requirements_conflict",
        "checked": checked,
        "blocking": blocking,
        "requested_specs": requested_specs,
        "candidate_specs": candidate_specs,
    }


def filter_candidates_against_technical_requirements(
    context: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    max_items: int = 10,
) -> Dict[str, Any]:
    """
    Filtra candidatos que contradicen especificaciones técnicas explícitas.

    Regla comercial/técnica:
    - Si el cliente dio una especificación numérica clara, por ejemplo 100 m,
      y existen productos con evidencia explícita que cumplen, se priorizan
      SOLO esos productos.
    - Los productos sin evidencia de esa especificación no se recomiendan
      en esa respuesta, para evitar mezclar opciones irrelevantes.
    - Si no existe ningún producto con evidencia suficiente, se conservan
      candidatos compatibles/no bloqueados para poder ofrecer alternativas.
    """
    if not isinstance(candidates, list):
        candidates = []

    validation_records: List[Dict[str, Any]] = []
    blocked_results: List[Dict[str, Any]] = []
    compatible_with_required_evidence: List[Dict[str, Any]] = []
    compatible_without_required_evidence: List[Dict[str, Any]] = []

    required_dimensions_global: List[str] = []

    for candidate in candidates:
        validation = validate_candidate_against_technical_requirements(
            context=context,
            candidate=candidate,
        )

        requested_specs = validation.get("requested_specs", {})
        candidate_specs = validation.get("candidate_specs", {})

        required_dimensions = [
            dimension
            for dimension, values in requested_specs.items()
            if isinstance(values, list) and len(values) > 0
        ]

        for dimension in required_dimensions:
            if dimension not in required_dimensions_global:
                required_dimensions_global.append(dimension)

        has_candidate_evidence_for_required = any(
            isinstance(candidate_specs.get(dimension), list)
            and len(candidate_specs.get(dimension, [])) > 0
            for dimension in required_dimensions
        )

        record = {
            "candidate": candidate,
            "candidate_code": (
                candidate.get("CODIGO")
                or candidate.get("codigo")
                or ""
            ),
            "candidate_name": (
                candidate.get("NOMBRE_PRODUCTO")
                or candidate.get("nombre")
                or candidate.get("DESCRIPCION_CORTA_PRE")
                or ""
            ),
            "validation": validation,
            "required_dimensions": required_dimensions,
            "has_candidate_evidence_for_required": has_candidate_evidence_for_required,
        }

        validation_records.append(record)

        if validation.get("compatible") is not True:
            blocked_results.append(candidate)
            continue

        if required_dimensions and has_candidate_evidence_for_required:
            compatible_with_required_evidence.append(candidate)
        else:
            compatible_without_required_evidence.append(candidate)

    # --------------------------------------------------------
    # Decisión final:
    # Si hay requerimiento numérico explícito y existen candidatos con
    # evidencia de cumplimiento, mostramos solo esos.
    # --------------------------------------------------------
    if required_dimensions_global and compatible_with_required_evidence:
        compatible_results = compatible_with_required_evidence
        selection_reason = "compatible_with_required_numeric_evidence"
    else:
        compatible_results = (
            compatible_with_required_evidence
            + compatible_without_required_evidence
        )
        selection_reason = (
            "no_required_numeric_evidence_found"
            if required_dimensions_global
            else "no_numeric_requirement_present"
        )

    validations = []

    for record in validation_records:
        validations.append(
            {
                "candidate_code": record.get("candidate_code"),
                "candidate_name": record.get("candidate_name"),
                "required_dimensions": record.get("required_dimensions"),
                "has_candidate_evidence_for_required": record.get(
                    "has_candidate_evidence_for_required"
                ),
                "validation": record.get("validation"),
            }
        )

    return {
        "ok": True,
        "version": VALIDATOR_VERSION,
        "input_count": len(candidates),
        "compatible_count": len(compatible_results),
        "blocked_count": len(blocked_results),
        "compatible_results": compatible_results[:max_items],
        "blocked_results": blocked_results,
        "validations": validations,
        "required_dimensions": required_dimensions_global,
        "selection_reason": selection_reason,
    }