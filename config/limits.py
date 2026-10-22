"""Límites rígidos. Ningún módulo (ni la IA ni la configuración) puede superarlos.

Cambiar este archivo es una decisión humana que pasa por revisión de código.
"""
from decimal import Decimal

APALANCAMIENTO_MAX = Decimal("2")
RIESGO_POR_OPERACION_MAX_PCT = Decimal("2")
PERDIDA_DIARIA_MAX_PCT = Decimal("10")
POSICIONES_ABIERTAS_MAX = 4
MODOS = ("simulacion", "testnet", "real")
