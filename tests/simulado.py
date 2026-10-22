"""Respuestas simuladas con el mismo formato que la documentación oficial de Binance (sin red)."""
from __future__ import annotations

import json

import httpx

AHORA_MS = 1_760_000_040_000          # instante fijo para las pruebas
MIN = 60_000
BASE_VELA = (AHORA_MS // MIN) * MIN   # apertura de la vela en curso


def kline(apertura_ms: int, o="100", h="101", l="99", c="100.5", v="10"):
    return [apertura_ms, o, h, l, c, v, apertura_ms + MIN - 1, "1000", 50, "5", "500", "0"]


def klines(n=5, **kw):
    return [kline(BASE_VELA - (n - 1 - i) * MIN, **kw) for i in range(n)]


def depth(ts=AHORA_MS):
    return {"lastUpdateId": 1027024, "E": ts, "T": ts - 2,
            "bids": [["100.40", "1.5"], ["100.30", "2"]], "asks": [["100.60", "1"], ["100.70", "3"]]}


def premium_index(ts=AHORA_MS, mark="100.50", indice="100.45"):
    return {"symbol": "BTCUSDT", "markPrice": mark, "indexPrice": indice, "estimatedSettlePrice": indice,
            "lastFundingRate": "0.00010000", "interestRate": "0.00010000",
            "nextFundingTime": AHORA_MS + 3_600_000, "time": ts}


def funding_hist():
    return [{"symbol": "BTCUSDT", "fundingRate": "0.00010000", "fundingTime": AHORA_MS - 28_800_000,
             "markPrice": "100.1"}]


def transporte(registro: list | None = None, estado: int = 200, cabeceras: dict | None = None,
               ajustes: dict | None = None):
    """MockTransport que contesta según la ruta y guarda cada solicitud en `registro`."""
    ajustes = ajustes or {}

    def manejar(req: httpx.Request) -> httpx.Response:
        if registro is not None:
            registro.append(req)
        h = {"X-MBX-USED-WEIGHT-1M": "7", **(cabeceras or {})}
        if estado != 200:
            return httpx.Response(estado, headers=h, json={"code": -1003, "msg": "Too many requests"})
        ruta = req.url.path
        cuerpo = ajustes.get(ruta) or {
            "/fapi/v1/time": {"serverTime": AHORA_MS},
            "/fapi/v1/klines": klines(min(int(req.url.params.get("limit", 5)), 100)),
            "/fapi/v1/depth": depth(),
            "/fapi/v1/premiumIndex": premium_index(),
            "/fapi/v1/fundingRate": funding_hist(),
        }.get(ruta)
        if cuerpo is None:
            return httpx.Response(404, json={"msg": "no existe"})
        return httpx.Response(200, headers=h, json=cuerpo)

    return httpx.MockTransport(manejar)


def ws_kline(simbolo="BTCUSDT", apertura=BASE_VELA, c="100.5", cerrada=False):
    return json.dumps({"stream": f"{simbolo.lower()}@kline_1m", "data": {
        "e": "kline", "E": AHORA_MS, "s": simbolo, "k": {
            "t": apertura, "T": apertura + MIN - 1, "s": simbolo, "i": "1m", "f": 1, "L": 2,
            "o": "100", "c": c, "h": "101", "l": "99", "v": "10", "n": 2, "x": cerrada,
            "q": "1000", "V": "5", "Q": "500", "B": "0"}}})


def ws_mark(simbolo="BTCUSDT", ts=AHORA_MS):
    return json.dumps({"stream": f"{simbolo.lower()}@markPrice@1s", "data": {
        "e": "markPriceUpdate", "E": ts, "s": simbolo, "p": "100.50", "i": "100.45", "P": "100.46",
        "r": "0.00010000", "T": AHORA_MS + 3_600_000}})


def ws_depth(simbolo="BTCUSDT", ts=AHORA_MS):
    return json.dumps({"stream": f"{simbolo.lower()}@depth20@500ms", "data": {
        "e": "depthUpdate", "E": ts, "T": ts - 1, "s": simbolo, "U": 10, "u": 12, "pu": 9,
        "b": [["100.40", "1.5"]], "a": [["100.60", "1"]]}})


class ConexionFalsa:
    """Imita `websockets.connect(url)`: entrega mensajes y luego se corta o se queda abierta."""

    def __init__(self, mensajes, cortar_con: Exception | None = None, quedarse_abierta=False):
        self.mensajes, self.cortar_con, self.quedarse_abierta = list(mensajes), cortar_con, quedarse_abierta

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        import asyncio
        for m in self.mensajes:
            yield m
        if self.cortar_con:
            raise self.cortar_con
        while self.quedarse_abierta:
            await asyncio.sleep(0.01)
