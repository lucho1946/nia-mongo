# ============================================================
# services/ai.py
# Responsabilidad única: toda la lógica de inteligencia de NIA.
#
# VERSIÓN 0.2:
# - Cliente OpenAI reutilizable con patrón lazy
# - SYSTEM_PROMPT completo con reglas comerciales de VIA Industrial
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
#
# LO QUE NO HACE TODAVÍA (Fase 2):
# - Identificación de cliente por NIT o celular
# - Clasificación Bronce/Platino/Oro
# - Notificación automática al asesor asignado
# - Pre-órdenes con datos del cliente
# ============================================================

from openai import OpenAI
import os
import logging

logger = logging.getLogger(__name__)

# Cliente OpenAI reutilizable — un solo cliente por proceso
_client: OpenAI | None = None


def get_ai_client() -> OpenAI:
    """
    Retorna el cliente OpenAI reutilizable.
    Patrón lazy — se crea solo cuando se necesita por primera vez.
    Un solo cliente por proceso — no uno por request.
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
# SYSTEM PROMPT PRINCIPAL
# Define la personalidad y reglas de NIA como asesora comercial.
# Separado del código para ajustarlo sin tocar la lógica.
# ============================================================

SYSTEM_PROMPT = """IDENTIDAD Y ROL

Eres NIA, asesora comercial femenina del equipo de VIA Industrial — empresa colombiana especializada en instrumentación, medición, automatización y equipos industriales ubicada en Bogotá, Colombia, con envíos a todo el país y Latinoamérica.

Tu función es atender al cliente, entender su necesidad, apoyar el proceso comercial, facilitar el avance de la negociación, aumentar la probabilidad de cierre, mantener coherencia en la conversación, reducir abandono y detectar oportunidades de compra.

No actúas como soporte pasivo ni chatbot informativo. Actúas como la mejor vendedora del mundo con enfoque técnico-comercial y orientación al cierre.

Comunícate en femenino cuando hagas referencia a ti misma. No menciones que eres una IA a menos que te lo pregunten directamente.

OBJETIVO PRINCIPAL: cerrar ventas.

---

ESTILO DE RESPUESTA

Responde siempre de forma breve, clara, directa, cordial, profesional y comercial.

Reglas clave:
- No repitas información que el cliente ya confirmó
- No reformules toda la conversación en cada respuesta
- Evita muletillas como "Perfecto", "Excelente", "Muy bien"
- Ve directo al punto sin rodeos
- Haz preguntas solo cuando falte información crítica
- Cuando tengas suficiente información, avanza sin pedir confirmaciones innecesarias
- Cada respuesta debe generar avance hacia especificación, cotización o cierre
- No expliques por qué haces una pregunta
- Máximo 4 líneas por respuesta salvo que el cliente pida detalle técnico
- No uses emojis decorativos

---

REGLA MAESTRA DE NEGOCIO

Tu objetivo no es solo responder. Tu objetivo es hacer avanzar la conversación hacia una acción útil.

Antes de responder, valida internamente:
1. ¿Qué necesita realmente este cliente?
2. ¿En qué etapa del proceso está?
3. ¿Qué acción concreta puedo provocar ahora?
4. ¿Estoy dejando un siguiente paso claro?
5. ¿Estoy ayudando a cerrar o estoy frenando?

Si la respuesta solo informa y no genera avance, mejórala antes de enviarla.

---

VELOCIDAD COMERCIAL

Si ya tienes información suficiente para avanzar, avanza sin esperar información perfecta. No frenes el proceso por datos menores que no bloquean el siguiente paso. Si puedes avanzar, avanza.

---

REGLA DE SIMPLIFICACIÓN

Responde de la forma más simple posible sin perder utilidad comercial. Una sola pregunta útil en lugar de tres. Si puedes decirlo con menos palabras, hazlo.

Ejemplo correcto: "¿Qué cantidad necesitas?"
Ejemplo incorrecto: "¿Podrías por favor indicarme cuántas unidades requieres para poder ayudarte de una mejor manera?"

---

DIAGNÓSTICO ANTES DE RECOMENDAR

Si el cliente es ambiguo, haz una sola pregunta corta y estratégica para aterrizar la necesidad. Prioriza preguntar por:
- Aplicación o uso específico
- Variable a medir, controlar o resolver
- Rango, voltaje, presión, capacidad o conexión según aplique
- Cantidad

Máximo 3 preguntas en toda la conversación antes de buscar y recomendar. Si ya hiciste 3 preguntas, busca con la información disponible.

Si el cliente tiene un código exacto de VIA Industrial (formato P + 6 números o 6 dígitos numéricos), busca directamente por ese código sin hacer preguntas.

---

REGLAS TÉCNICAS DE DATOS — VIA INDUSTRIAL

PRECIO:
- Solo muestra precio si PV_FECHA tiene menos de 12 meses. Si tiene más de 12 meses sin actualizar o no hay fecha, di "Voy a validar el valor para darte una respuesta precisa."
- Nunca inventes precios. Si el precio dice "Consultarnos", indica que se validará.
- Presenta el precio como precio sin IVA de forma natural.

STOCK Y DISPONIBILIDAD:
- Informa stock real por sede: Bogotá y Cali por separado cuando esté disponible.
- Nunca inventes stock ni disponibilidad.

TIEMPO DE ENTREGA:
- Solo comunica tiempo de entrega si está disponible en los datos del producto.
- Si el cliente objeta el tiempo, indica que se puede revisar para validar si es posible mejorarlo.

PRODUCTOS:
- Solo recomienda productos del catálogo real de VIA Industrial.
- Presenta máximo 3 opciones cuando hay varias alternativas.
- Para cada producto incluye: nombre, código, referencia, precio y disponibilidad.
- Si el producto exacto no tiene stock, ofrece equivalentes disponibles.
- Nunca inventes referencias, códigos ni características no verificadas.
- Si no encuentras productos, di: "Voy a validar la información para darte una respuesta precisa." y mantén el siguiente paso útil.

---

DETECCIÓN DE INTENCIÓN

Cuando el cliente exprese intención de compra con frases como "quiero comprar", "quiero cotizar", "me interesa", "lo quiero pedir", activa modo de cierre y solicita solo lo mínimo necesario: producto, cantidad y datos básicos.

Cuando el cliente pida hablar con un asesor, descuento, garantía o tiempo de entrega especial, registra la solicitud y conecta con el equipo comercial.

---

FALLBACK

Si no tienes información confirmada, responde:
- "Voy a validar la información para darte una respuesta precisa."
- "En un momento confirmamos ese dato."

Siempre acompaña el fallback con una acción útil o pregunta que mantenga viva la negociación.

---

FILTRO DE USUARIOS

Si detectas que es un vendedor externo, competidor o bot, responde únicamente:
"Este canal es exclusivo para clientes de VIA Industrial."
No continúes la conversación.

---

CONTROL FINAL ANTES DE ENVIAR

Antes de enviar cada respuesta, valida internamente:
1. ¿Entendí la intención real del cliente?
2. ¿Mi respuesta ayuda a avanzar?
3. ¿Evité repetir preguntas ya respondidas?
4. ¿Dejé un siguiente paso claro?
5. ¿Si el cliente está listo para comprar, estoy cerrando y no frenando?
6. ¿Mi respuesta suena comercial, humana y útil?
7. ¿Estoy pidiendo solo lo que falta?
8. ¿Estoy simplificando en lugar de complicar?
9. ¿Estoy avanzando con la información suficiente que ya tengo?

Si la respuesta no cumple esto, mejórala antes de enviarla."""


# ============================================================
# PROMPT DE DECISIÓN
# Le dice a la IA cuándo preguntar y cuándo buscar.
# Temperature muy baja (0.1) para decisiones consistentes.
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
- Máximo 3 preguntas en toda la conversación — si ya hiciste 3 SIEMPRE elige BUSCAR
- Si el cliente da una referencia o código exacto SIEMPRE elige BUSCAR inmediatamente
- Si el cliente dice que no sabe o no tiene más datos SIEMPRE elige BUSCAR
- Si el cliente pide ver opciones o catálogo SIEMPRE elige BUSCAR
- Las preguntas deben ser técnicas y específicas — no genéricas como "¿qué necesita?"
- La query debe incluir TODOS los datos técnicos recopilados en la conversación"""


# ============================================================
# DETECCIÓN DE INTENCIÓN ESPECIAL
# Detección local — no llama a OpenAI para ahorrar tokens.
# ============================================================

def detectar_intencion_especial(mensaje: str) -> str | None:
    """
    Detecta intenciones especiales que requieren acción diferente al flujo normal.

    Retorna:
    - 'escalar_asesor'   → el cliente quiere hablar con un humano o pide descuento
    - 'generar_preorden' → el cliente quiere comprar o cotizar formalmente
    - 'bot_detectado'    → parece un vendedor externo, competidor o bot
    - None               → flujo normal de conversación técnica

    IMPORTANTE — keywords de compra vs información:
    Preguntar por disponibilidad o precio NO es intención de compra.
    Solo se detecta compra cuando el cliente expresa decisión de adquirir.
    """
    mensaje_lower = mensaje.lower().strip()

    # Vendedores externos, competidores o bots
    # Detectados primero — tienen prioridad sobre todo lo demás
    keywords_bot = [
        "soy vendedor", "soy proveedor", "ofrezco productos",
        "vendo equipos", "distribuidor de", "mejor precio que via",
        "propuesta comercial", "oferta para via"
    ]

    # Intención de compra real — el cliente decide adquirir
    # NO incluye preguntas de información como "¿tienen?" o "¿está disponible?"
    keywords_compra = [
        "quiero comprar", "quiero cotizar", "me interesa comprarlo",
        "lo quiero pedir", "hacer un pedido", "orden de compra",
        "cotización formal", "quiero la cotización",
        "me lo pueden facturar", "proceder con la compra"
    ]

    # Solicitud de asesor humano o temas que requieren negociación
    keywords_asesor = [
        "hablar con", "comunicarme con", "necesito un asesor",
        "quiero hablar con alguien", "persona real", "humano",
        "ejecutivo comercial", "representante",
        "precio especial", "descuento", "negociar precio",
        "garantía", "tiempo de entrega", "cuándo llega",
        "despacho", "envío a"
    ]

    # Verificar en orden de prioridad
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

    Parámetros:
    - historial: lista completa de mensajes de la conversación
    - preguntas_hechas: cuántas preguntas ya hizo NIA en esta sesión

    Retorna:
    - {"accion": "PREGUNTAR", "pregunta": "..."}
    - {"accion": "BUSCAR",    "query":   "..."}

    Fallbacks robustos:
    1. Si preguntas_hechas >= 3 → BUSCAR sin llamar a OpenAI
    2. Si OpenAI falla → BUSCAR con último mensaje del cliente
    3. Si respuesta tiene formato inesperado → BUSCAR con historial completo
    4. Si PREGUNTAR pero sin texto de pregunta → BUSCAR con historial
    """

    # Forzar búsqueda si ya se hicieron 3 preguntas — sin gastar tokens
    if preguntas_hechas >= 3:
        mensajes_cliente = [
            m["content"] for m in historial if m["role"] == "user"
        ]
        logger.info("3 preguntas alcanzadas — forzando BUSCAR")
        return {"accion": "BUSCAR", "query": " ".join(mensajes_cliente)}

    try:
        mensajes = [{"role": "system", "content": PROMPT_DECISION}] + historial

        response = get_ai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes,
            max_tokens=150,
            temperature=0.1,
        )

        texto = response.choices[0].message.content.strip()
        logger.info(f"Decisión IA raw: {texto[:150]}")

        # Parsear PREGUNTAR
        if "ACCION: PREGUNTAR" in texto:
            pregunta = ""
            for linea in texto.split("\n"):
                if linea.strip().startswith("PREGUNTA:"):
                    pregunta = linea.replace("PREGUNTA:", "").strip()
                    break

            # Si tiene pregunta válida la retornamos
            if pregunta:
                return {"accion": "PREGUNTAR", "pregunta": pregunta}

            # Si dice PREGUNTAR pero no hay texto de pregunta → BUSCAR
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

            # Si dice BUSCAR pero no hay query → usar historial
            logger.warning("BUSCAR sin query — usando historial completo")

        # Formato completamente inesperado → BUSCAR con historial
        logger.warning(f"Formato inesperado de IA: {texto[:100]}")
        mensajes_cliente = [
            m["content"] for m in historial if m["role"] == "user"
        ]
        return {"accion": "BUSCAR", "query": " ".join(mensajes_cliente)}

    except Exception as e:
        logger.error(f"Error en decidir_accion: {e}")
        # Fallback final — buscar con el último mensaje del cliente
        ultimo = next(
            (m["content"] for m in reversed(historial) if m["role"] == "user"),
            ""
        )
        return {"accion": "BUSCAR", "query": ultimo}


# ============================================================
# GENERACIÓN DE RECOMENDACIÓN
# ============================================================

def generar_recomendacion(historial: list, contexto_productos: str) -> str:
    """
    Genera la respuesta final de NIA con los productos encontrados.

    Parámetros:
    - historial: conversación completa para contexto
    - contexto_productos: string con productos de MongoDB
      (código, referencia, precio, stock, características)

    Maneja el caso de contexto vacío — NIA responde honestamente
    sin inventar productos.
    """
    # Si no hay productos NIA lo maneja con honestidad
    if not contexto_productos or contexto_productos.strip() == "":
        instruccion_productos = (
            "No encontré productos en el catálogo que coincidan exactamente. "
            "Pide al cliente más detalles técnicos o sugiere contactar a un asesor."
        )
    else:
        instruccion_productos = (
            f"PRODUCTOS DISPONIBLES EN CATÁLOGO DE VIA INDUSTRIAL:\n"
            f"{contexto_productos}\n\n"
            f"Recomienda máximo 3 productos ordenados de mayor a menor relevancia. "
            f"Para cada uno incluye: nombre, código, referencia, precio y disponibilidad. "
            f"Si el precio dice Consultarnos indícalo y sugiere contactar al asesor. "
            f"Si hay stock en Bogotá o Cali menciónalo explícitamente. "
            f"Si hay equivalentes y el producto no tiene stock, ofrécelos."
        )

    mensajes = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": instruccion_productos}
    ] + historial

    try:
        response = get_ai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes,
            max_tokens=700,
            temperature=0.3,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Error en generar_recomendacion: {e}")
        raise


# ============================================================
# MENSAJES ESTÁNDAR DE NIA
# Centralizados aquí para consistencia en toda la aplicación.
# ============================================================

# Respuesta cuando se detecta bot o vendedor externo
RESPUESTA_BOT = (
    "Este canal es exclusivo para clientes de VIA Industrial. "
    "Si usted es cliente y necesita asesoría, con gusto le ayudamos."
)

# Respuesta cuando el cliente pide un asesor humano
# Fase 1: avisa que se registró la solicitud
# Fase 2: conectará automáticamente con el asesor asignado
RESPUESTA_ESCALACION = (
    "Entendido. He registrado su solicitud para que un asesor comercial "
    "de VIA Industrial se comunique con usted. "
    "¿Desea dejarnos su nombre y número de contacto para que le llamemos?"
)

# Respuesta cuando el cliente quiere cotizar
# Fase 1: avisa que se registró el interés
# Fase 2: generará pre-orden automática con notificación al asesor
RESPUESTA_PREORDEN = (
    "Perfecto, con mucho gusto. Para generar su cotización necesito "
    "algunos datos: ¿cuál es su nombre y el nombre de su empresa?"
)