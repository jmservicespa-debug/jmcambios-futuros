import asyncio
from decimal import Decimal

from futuros.data import ws
from futuros.data.modelos import Libro, MarkPrice, Vela
from simulado import ConexionFalsa, ws_depth, ws_kline, ws_mark


def test_urls_usan_rutas_market_y_public():
    u = ws.urls_streams(["BTCUSDT", "ethusdt"])
    assert u["market"] == ("wss://fstream.binance.com/market/stream?streams="
                           "btcusdt@kline_1m/ethusdt@kline_1m/btcusdt@markPrice@1s/ethusdt@markPrice@1s")
    assert u["public"] == "wss://fstream.binance.com/public/stream?streams=btcusdt@depth20@500ms/ethusdt@depth20@500ms"


def test_parsear_mensajes():
    v = ws.parsear_mensaje(ws_kline(cerrada=True))
    m = ws.parsear_mensaje(ws_mark())
    lb = ws.parsear_mensaje(ws_depth())
    assert isinstance(v, Vela) and v.cerrada and v.cierre == Decimal("100.5")
    assert isinstance(m, MarkPrice) and m.mark == Decimal("100.50") and m.funding == Decimal("0.0001")
    assert isinstance(lb, Libro) and lb.mejor_bid == Decimal("100.40")
    assert ws.parsear_mensaje('{"stream":"x","data":{"e":"otro"}}') is None


def test_reconecta_y_avisa_desconexion():
    recibidos, estados, esperas = [], [], []
    conexiones = iter([ConexionFalsa([ws_mark()], cortar_con=ConnectionResetError("se cayó internet")),
                       ConexionFalsa([ws_mark(), ws_depth()])])

    async def dormir(s):
        esperas.append(s)

    asyncio.run(ws.escuchar("market", "wss://x", recibidos.append, lambda *a: estados.append(a),
                            conectar=lambda url: next(conexiones), reintentos_max=1, dormir=dormir))
    assert len(recibidos) == 3
    assert [e[1] for e in estados] == [True, False, True, False]
    assert "se cayó internet" in estados[1][2]
    assert esperas == [1.0]


def test_espera_crece_si_no_logra_conectar():
    esperas = []

    def falla(url):
        raise OSError("sin red")

    async def dormir(s):
        esperas.append(s)

    asyncio.run(ws.escuchar("public", "wss://x", lambda d: None, lambda *a: None, conectar=falla,
                            reintentos_max=6, dormir=dormir))
    assert esperas == [1.0, 2.0, 4.0, 8.0, 16.0, 30]
