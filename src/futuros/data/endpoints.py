"""Endpoints públicos (solo lectura) de Binance USDⓈ-M Futures.

Todos salen de la documentación oficial:
https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api
https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams

Ninguno necesita llave API. No hay aquí nada que envíe órdenes.
"""
from __future__ import annotations

REST_BASE = "https://fapi.binance.com"

# Rutas REST de datos de mercado (GET, sin firma).
TIEMPO = "/fapi/v1/time"                # hora del servidor, peso 1
VELAS = "/fapi/v1/klines"               # velas, peso según limit
LIBRO = "/fapi/v1/depth"                # libro de órdenes, peso según limit
MARK_PRICE = "/fapi/v1/premiumIndex"    # mark price + último funding, peso 1 con symbol
FUNDING = "/fapi/v1/fundingRate"        # historial de funding (límite propio 500 / 5 min / IP)

# WebSocket: desde 2026 Binance exige rutas separadas por tipo de dato.
#   /public -> datos de alta frecuencia (libro)
#   /market -> datos normales (velas, mark price)
WS_BASE = "wss://fstream.binance.com"
WS_PUBLIC = WS_BASE + "/public"
WS_MARKET = WS_BASE + "/market"

INTERVALOS_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
}
LIMITES_LIBRO = (5, 10, 20, 50, 100, 500, 1000)
VELAS_LIMITE_MAX = 1500


def peso_velas(limit: int) -> int:
    if limit < 100:
        return 1
    if limit < 500:
        return 2
    if limit <= 1000:
        return 5
    return 10


def peso_libro(limit: int) -> int:
    if limit <= 50:
        return 2
    if limit == 100:
        return 5
    if limit == 500:
        return 10
    return 20


def peso_mark_price(con_simbolo: bool = True) -> int:
    return 1 if con_simbolo else 10
