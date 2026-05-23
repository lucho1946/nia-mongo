# =========================================================
# SEARCH ADAPTER — NIA OS
# =========================================================

from services.search import (
    buscar_productos,
    buscar_por_codigo_exacto,
)


def search_products(query: str):
    """
    Adaptador del nuevo cerebro modular
    hacia el motor de búsqueda actual.
    """

    return buscar_productos(query)


def search_exact_code(code: str):
    """
    Búsqueda exacta de código industrial.
    """

    return buscar_por_codigo_exacto(code)