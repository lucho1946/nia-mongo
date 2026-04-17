# ============================================================
# limpiar_productos.py
# Script de limpieza del catálogo de productos.
# Lee productos.json, elimina registros corruptos o inútiles,
# normaliza campos y genera productos_limpio.json listo para
# reimportar a MongoDB.
# Ejecutar UNA sola vez localmente, nunca en producción.
# ============================================================

import json
import re
import unicodedata

ARCHIVO_ENTRADA = "productos.json"
ARCHIVO_SALIDA  = "productos_limpio.json"

# ============================================================
# UTILIDADES
# ============================================================

def normalizar(texto: str) -> str:
    texto = str(texto).strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", texto).strip()

def limpiar_precio(precio) -> float | None:
    """Convierte precio a número. Retorna None si no es válido."""
    try:
        valor = float(str(precio).replace(",", "").replace(" ", ""))
        return valor if valor >= 0 else None
    except:
        return None

def es_fecha(texto: str) -> bool:
    """Detecta si un campo contiene una fecha — señal de dato corrompido."""
    return bool(re.search(r"\d{4}-\d{2}-\d{2}", str(texto)))

def es_valido(p: dict) -> bool:
    """
    Define si un producto es válido para conservar.
    Criterios de eliminación:
    - Sin código
    - Sin nombre o nombre menor a 3 caracteres
    - Nombre que parece una fecha (campo desplazado)
    - Marca que parece una fecha (campo desplazado)
    - Código que contiene saltos de línea (registros concatenados)
    """
    codigo  = str(p.get("codigo", "")).strip()
    nombre  = str(p.get("nombre", "")).strip()
    marca   = str(p.get("marca", "")).strip()

    if not codigo or len(codigo) < 2:
        return False
    if "\n" in codigo or "\r" in codigo:
        return False
    if len(nombre) < 3:
        return False
    if es_fecha(nombre):
        return False
    if es_fecha(marca):
        return False
    return True

def limpiar_producto(p: dict) -> dict:
    """Normaliza y limpia todos los campos de un producto válido."""
    precio_limpio = limpiar_precio(p.get("precio"))

    return {
        "codigo":                  normalizar(p.get("codigo", "")),
        "referencia_limpia":       normalizar(p.get("referencia_limpia", "")),
        "texto_buscado_expandido": normalizar(p.get("texto_buscado_expandido", "")),
        "marca":                   normalizar(p.get("marca", "")).lower(),
        "nombre":                  normalizar(p.get("nombre", "")),
        "descripcion":             normalizar(p.get("descripcion", "")),
        "categoria":               normalizar(p.get("categoria", "")).lower(),
        "precio":                  precio_limpio,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"Cargando {ARCHIVO_ENTRADA}...")
    with open(ARCHIVO_ENTRADA, "r", encoding="utf-8") as f:
        data = json.load(f)

    productos_raw = data if isinstance(data, list) else data.get("productos", [])
    total_original = len(productos_raw)
    print(f"Total registros originales: {total_original:,}")

    # --- Filtrar corruptos ---
    validos = [p for p in productos_raw if es_valido(p)]
    eliminados = total_original - len(validos)
    print(f"Registros eliminados (corruptos): {eliminados:,}")

    # --- Limpiar campos ---
    limpios = [limpiar_producto(p) for p in validos]

    # --- Eliminar duplicados por código ---
    vistos = set()
    sin_duplicados = []
    for p in limpios:
        codigo = p["codigo"]
        if codigo not in vistos:
            vistos.add(codigo)
            sin_duplicados.append(p)

    duplicados = len(limpios) - len(sin_duplicados)
    print(f"Registros duplicados eliminados: {duplicados:,}")
    print(f"Total registros finales limpios: {len(sin_duplicados):,}")

    # --- Guardar resultado ---
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        json.dump(sin_duplicados, f, ensure_ascii=False, indent=2)

    print(f"\nArchivo generado: {ARCHIVO_SALIDA}")

    # --- Reporte de muestra ---
    print("\n--- Muestra de primeros 3 productos limpios ---")
    for p in sin_duplicados[:3]:
        print(json.dumps(p, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()