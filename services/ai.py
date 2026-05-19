# ============================================================
# services/ai.py
# Responsabilidad única: toda la lógica de inteligencia de NIA.
#
# VERSIÓN 0.5
# Cambios:
# - Log de uso OpenAI: tokens, modelo, response_id y costo estimado opcional
# - Log end to end seguro para decisiones y recomendaciones
# - Detección de saludo puro más estricta
# - "Hola, necesito..." ya no se clasifica como saludo
# - PROMPT_DECISION afinado para saludos limpios vs intención comercial
# - Fallbacks robustos mantenidos
#
# VERSIÓN 0.4
# - PROMPT_DECISION actualizado con reglas para saludos
# - Manejo de mensajes sin relación con productos industriales
#
# VERSIÓN 0.3
# - Cliente OpenAI reutilizable con patrón lazy
# - SYSTEM_PROMPT cargado desde archivo externo
# - PROMPT_DECISION para decidir si preguntar o buscar
# - decidir_accion(): llama a OpenAI y parsea la decisión con fallbacks robustos
# - generar_recomendacion(): genera respuesta con productos reales
# - detectar_intencion_especial(): detecta escalación, compra y bots
#
# FLUJO DE NIA:
# 1. Cliente escribe
# 2. detectar_intencion_especial() — ¿es bot? ¿quiere asesor? ¿quiere comprar?
# 3. Si flujo normal → decidir_accion()
#    → PREGUNTAR: NIA hace una pregunta técnica (máximo 3)
#    → BUSCAR: NIA busca en MongoDB y recomienda
# 4. generar_recomendacion() — genera respuesta con productos reales
# ============================================================

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from openai import OpenAI

from services.audit import registrar_traza_azure

logger = logging.getLogger(__name__)

# ============================================================
# UTILIDAD DE TRAZAS SEGURAS
# ============================================================
# Si el log a archivo falla, no debe romper el flujo de NIA.
# ============================================================


def _registrar_traza_segura(etapa: str, payload: dict[str, Any]) -> None:
    """
    Registra trazas en Azure/archivo sin afectar el flujo principal
    si el sistema de logging falla.
    """
    try:
        registrar_traza_azure(etapa, payload)
    except Exception as e:
        logger.warning("No se pudo registrar traza %s: %s", etapa, e)


def _extraer_uso_openai(response: Any) -> dict[str, Any]:
    """
    Extrae el bloque usage de la respuesta de OpenAI de forma segura.

    Devuelve algo como:
    {
        "prompt_tokens": 123,
        "completion_tokens": 456,
        "total_tokens": 579
    }
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}

    if hasattr(usage, "model_dump"):
        try:
            datos = usage.model_dump(exclude_none=True)
            return datos if isinstance(datos, dict) else {}
        except TypeError:
            datos = usage.model_dump()
            return datos if isinstance(datos, dict) else {}

    if isinstance(usage, dict):
        return {k: v for k, v in usage.items() if v is not None}

    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _estimar_costo_desde_uso(uso: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula un costo estimado opcional si defines tarifas por env.

    Variables esperadas:
    - OPENAI_INPUT_PRICE_PER_1M_TOKENS_USD
    - OPENAI_OUTPUT_PRICE_PER_1M_TOKENS_USD

    Si no existen, no se estima costo.
    """
    precio_entrada = os.getenv("OPENAI_INPUT_PRICE_PER_1M_TOKENS_USD")
    precio_salida = os.getenv("OPENAI_OUTPUT_PRICE_PER_1M_TOKENS_USD")

    if not precio_entrada or not precio_salida:
        return {}

    try:
        prompt_tokens = float(uso.get("prompt_tokens") or 0)
        completion_tokens = float(uso.get("completion_tokens") or 0)

        costo = (
            (prompt_tokens / 1_000_000.0) * float(precio_entrada)
            + (completion_tokens / 1_000_000.0) * float(precio_salida)
        )
        return {"costo_estimado_usd": round(costo, 6)}
    except (TypeError, ValueError):
        return {}


# ============================================================
# CARGA DEL PROMPT MAESTRO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE_DIR / "prompts" / "prompt_maestro_nia.txt"


def cargar_prompt_maestro() -> str:
    """
    Carga el prompt maestro oficial de NIA desde archivo externo.
    """
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró el prompt maestro en: {PROMPT_PATH}"
        )

    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("El prompt maestro está vacío.")

    logger.info("Prompt maestro cargado correctamente")
    return prompt


# Prompt maestro oficial de NIA
SYSTEM_PROMPT = cargar_prompt_maestro()

# Cliente OpenAI reutilizable — un solo cliente por proceso
_client: OpenAI | None = None


def get_ai_client() -> OpenAI:
    """
    Retorna el cliente OpenAI reutilizable.
    Patrón lazy — se crea solo cuando se necesita por primera vez.
    Falla rápido si la API key no está configurada.
    """
    global _client

    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY no configurado. "
                "Agrégalo en Azure App Service → Variables de entorno."
            )
        _client = OpenAI(api_key=api_key)
        logger.info("Cliente OpenAI inicializado")

    return _client


# ============================================================
# PROMPT DE DECISIÓN
# ============================================================

PROMPT_DECISION = """Eres NIA, asesora comercial de VIA Industrial.
VIA Industrial vende equipos de instrumentación, medición, automatización y equipos industriales en general.

Analiza la conversación y decide qué hacer:

OPCIÓN A — PREGUNTAR:
Si necesitas más información técnica para encontrar el producto correcto en el catálogo,
genera UNA sola pregunta técnica, corta y concisa.
Las preguntas deben ser sobre: aplicación específica, voltaje, presión, rango de medición,
capacidad, temperatura, conexión, marca preferida o referencia del equipo.
Responde EXACTAMENTE así (sin texto adicional antes ni después):
ACCION: PREGUNTAR
PREGUNTA: [tu pregunta aquí]

OPCIÓN B — BUSCAR:
Si ya tienes suficiente contexto para buscar en el catálogo,
construye una query con todos los datos técnicos recopilados.
Responde EXACTAMENTE así (sin texto adicional antes ni después):
ACCION: BUSCAR
QUERY: [términos de búsqueda aquí]

REGLAS CRÍTICAS:
- Si el mensaje es un saludo limpio y sin intención comercial ("hola", "buenos días", "buenas", etc.) SIEMPRE elige PREGUNTAR y responde con: "Hola, soy NIA, asesora comercial de VIA Industrial. ¿En qué producto puedo ayudarte hoy?"
- Si el mensaje contiene saludo + necesidad comercial (por ejemplo: "Hola, necesito una válvula...") NO lo trates como saludo puro; prioriza la intención comercial
- Si el mensaje no tiene ninguna relación con productos industriales SIEMPRE elige PREGUNTAR preguntando en qué puede ayudar
- Máximo 3 preguntas en toda la conversación — si ya hiciste 3 SIEMPRE elige BUSCAR
- Si el cliente da una referencia o código exacto SIEMPRE elige BUSCAR inmediatamente
- Si el cliente dice que no sabe o no tiene más datos SIEMPRE elige BUSCAR
- Si el cliente pide ver opciones o catálogo SIEMPRE elige BUSCAR
- Las preguntas deben ser técnicas y específicas — no genéricas como "¿qué necesita?"
- La query debe incluir TODOS los datos técnicos recopilados en la conversación"""


# ============================================================
# DETECCIÓN DE INTENCIÓN ESPECIAL
# ============================================================

SALUDOS_PUROS = {
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "buenas",
    "hey",
    "hi",
    "hello",
    "good morning",
    "buen dia",
    "saludos",
    "hola buenas",
    "hola buenos dias",
    "hola buenas tardes",
    "hola buenas noches",
    "hola buen dia",
}


def normalizar_texto_simple(texto: str) -> str:
    """
    Normaliza texto para comparaciones simples:
    - minúsculas
    - sin acentos
    - sin espacios repetidos
    - sin signos de puntuación al inicio/fin
    """
    texto = str(texto).lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    texto = texto.strip(" \t\n\r,!.?¿¡:;")
    return texto


def es_saludo_puro(mensaje: str) -> bool:
    """
    Detecta solo saludos limpios, no mensajes mixtos.
    Ejemplo:
    - "hola" → True
    - "hola, necesito una válvula" → False
    """
    texto = normalizar_texto_simple(mensaje)
    return texto in SALUDOS_PUROS


def detectar_intencion_especial(mensaje: str) -> str | None:
    """
    Detecta intenciones especiales que requieren acción diferente al flujo normal.

    Retorna:
    - 'saludo'
    - 'escalar_asesor'
    - 'generar_preorden'
    - 'bot_detectado'
    - None
    """
    mensaje_lower = normalizar_texto_simple(mensaje)

    # Saludo puro primero. Si el mensaje trae intención comercial,
    # esta regla no debe activarse.
    if es_saludo_puro(mensaje):
        return "saludo"

    # Vendedores externos, competidores o bots
    keywords_bot = [
        "soy vendedor", "soy proveedor", "ofrezco productos",
        "vendo equipos", "distribuidor de", "mejor precio que via",
        "propuesta comercial", "oferta para via"
    ]

    # Intención de compra real — el cliente decide adquirir
    keywords_compra = [
        "quiero comprar", "quiero cotizar", "me interesa comprarlo",
        "lo quiero pedir", "hacer un pedido", "orden de compra",
        "cotizacion formal", "quiero la cotizacion",
        "me lo pueden facturar", "proceder con la compra"
    ]

    # Solicitud de asesor humano o temas que requieren negociación
    keywords_asesor = [
        "hablar con", "comunicarme con", "necesito un asesor",
        "quiero hablar con alguien", "persona real", "humano",
        "ejecutivo comercial", "representante",
        "precio especial", "descuento", "negociar precio",
        "garantia", "tiempo de entrega", "cuando llega",
        "despacho", "envio a"
    ]

    for kw in keywords_bot:
        if kw in mensaje_lower:
            return "bot_detectado"

    for kw in keywords_compra:
        if kw in mensaje_lower:
            return "generar_preorden"

    for kw in keywords_asesor:
        if kw in mensaje_lower:
            return "escalar_asesor"

    return None


# ============================================================
# DECISIÓN INTELIGENTE — PREGUNTAR O BUSCAR
# ============================================================

def decidir_accion(historial: list, preguntas_hechas: int) -> dict:
    """
    Consulta a la IA para decidir si debe hacer una pregunta técnica
    o buscar productos en el catálogo.
    """
    # Forzar búsqueda si ya se hicieron 3 preguntas — sin gastar tokens
    if preguntas_hechas >= 3:
        mensajes_cliente = [m["content"] for m in historial if m["role"] == "user"]
        query_forzada = " ".join(mensajes_cliente).strip()

        _registrar_traza_segura(
            "decidir_accion.forzado_buscar",
            {
                "preguntas_hechas": preguntas_hechas,
                "historial": historial,
                "query_forzada": query_forzada,
            },
        )

        logger.info("3 preguntas alcanzadas — forzando BUSCAR")
        return {"accion": "BUSCAR", "query": query_forzada}

    try:
        mensajes = [{"role": "system", "content": PROMPT_DECISION}] + historial

        _registrar_traza_segura(
            "decidir_accion.input",
            {
                "model": "gpt-4o-mini",
                "temperature": 0.1,
                "max_tokens": 150,
                "preguntas_hechas": preguntas_hechas,
                "historial": historial,
                "prompt_decision": PROMPT_DECISION,
            },
        )

        response = get_ai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes,
            max_tokens=150,
            temperature=0.1,
        )

        texto = (response.choices[0].message.content or "").strip()
        logger.info("Decisión IA raw: %s", texto[:150])

        uso = _extraer_uso_openai(response)
        payload_uso = {
            "model": getattr(response, "model", "gpt-4o-mini"),
            "response_id": getattr(response, "id", None),
            "usage": uso,
        }
        payload_uso.update(_estimar_costo_desde_uso(uso))

        if uso:
            _registrar_traza_segura("decidir_accion.usage", payload_uso)

        _registrar_traza_segura(
            "decidir_accion.output",
            {
                "model": "gpt-4o-mini",
                "raw_response": texto,
            },
        )

        # Parsear PREGUNTAR
        if "ACCION: PREGUNTAR" in texto:
            pregunta = ""
            for linea in texto.split("\n"):
                if linea.strip().startswith("PREGUNTA:"):
                    pregunta = linea.replace("PREGUNTA:", "").strip()
                    break

            if pregunta:
                return {"accion": "PREGUNTAR", "pregunta": pregunta}

            logger.warning("PREGUNTAR sin texto de pregunta — fallback a BUSCAR")

        # Parsear BUSCAR
        if "ACCION: BUSCAR" in texto:
            query = ""
            for linea in texto.split("\n"):
                if linea.strip().startswith("QUERY:"):
                    query = linea.replace("QUERY:", "").strip()
                    break

            if query:
                return {"accion": "BUSCAR", "query": query}

            logger.warning("BUSCAR sin query — usando historial completo")

        # Formato inesperado → BUSCAR con historial
        logger.warning("Formato inesperado de IA: %s", texto[:100])
        mensajes_cliente = [m["content"] for m in historial if m["role"] == "user"]
        return {"accion": "BUSCAR", "query": " ".join(mensajes_cliente)}

    except Exception as e:
        logger.error("Error en decidir_accion: %s", e)

        _registrar_traza_segura(
            "decidir_accion.error",
            {
                "error": str(e),
                "preguntas_hechas": preguntas_hechas,
                "historial": historial,
            },
        )

        ultimo = next((m["content"] for m in reversed(historial) if m["role"] == "user"), "")
        return {"accion": "BUSCAR", "query": ultimo}


# ============================================================
# GENERACIÓN DE RECOMENDACIÓN
# ============================================================

def generar_recomendacion(historial: list, contexto_productos: str) -> str:
    """
    Genera la respuesta final de NIA con los productos encontrados.
    """
    if not contexto_productos or contexto_productos.strip() == "":
        instruccion_productos = (
            "No encontré productos en el catálogo que coincidan exactamente. "
            "Pide al cliente más detalles técnicos o sugiere contactar a un asesor."
        )
    else:
        instruccion_productos = (
            "PRODUCTOS DISPONIBLES EN CATÁLOGO DE VIA INDUSTRIAL:\n"
            f"{contexto_productos}\n\n"
            "Recomienda máximo 3 productos ordenados de mayor a menor relevancia. "
            "Para cada uno incluye: nombre, código, referencia, precio y disponibilidad. "
            "Si el precio dice Consultarnos indícalo y sugiere contactar al asesor. "
            "Si hay stock en Bogotá o Cali menciónalo explícitamente. "
            "Si hay equivalentes y el producto no tiene stock, ofrécelos."
        )

    mensajes = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": instruccion_productos},
    ] + historial

    _registrar_traza_segura(
        "generar_recomendacion.input",
        {
            "model": "gpt-4o-mini",
            "temperature": 0.3,
            "max_tokens": 700,
            "historial": historial,
            "contexto_productos": contexto_productos,
            "system_prompt": SYSTEM_PROMPT,
            "instruccion_productos": instruccion_productos,
        },
    )

    try:
        response = get_ai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes,
            max_tokens=700,
            temperature=0.3,
        )

        respuesta = (response.choices[0].message.content or "").strip()

        uso = _extraer_uso_openai(response)
        payload_uso = {
            "model": getattr(response, "model", "gpt-4o-mini"),
            "response_id": getattr(response, "id", None),
            "usage": uso,
        }
        payload_uso.update(_estimar_costo_desde_uso(uso))

        if uso:
            _registrar_traza_segura("generar_recomendacion.usage", payload_uso)

        _registrar_traza_segura(
            "generar_recomendacion.output",
            {
                "model": "gpt-4o-mini",
                "respuesta_modelo": respuesta,
            },
        )

        return respuesta

    except Exception as e:
        logger.error("Error en generar_recomendacion: %s", e)

        _registrar_traza_segura(
            "generar_recomendacion.error",
            {
                "error": str(e),
                "historial": historial,
                "contexto_productos": contexto_productos,
            },
        )
        raise


# ============================================================
# MENSAJES ESTÁNDAR DE NIA
# ============================================================

RESPUESTA_BOT = (
    "Este canal es exclusivo para clientes de VIA Industrial. "
    "Si usted es cliente y necesita asesoría, con gusto le ayudamos."
)

RESPUESTA_ESCALACION = (
    "Entendido. He registrado su solicitud para que un asesor comercial "
    "de VIA Industrial se comunique con usted. "
    "¿Desea dejarnos su nombre y número de contacto para que le llamemos?"
)

RESPUESTA_PREORDEN = (
    "Perfecto, con mucho gusto. Para generar su cotización necesito "
    "algunos datos: ¿cuál es su nombre y el nombre de su empresa?"
)