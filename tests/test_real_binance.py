"""Verificación REAL contra Binance (opcional, necesita internet).

Se salta por defecto. Para correrla en tu PC (PowerShell):
    $env:FUTUROS_PRUEBA_REAL = "1"; pytest -q -m red
"""
import asyncio
import os
import time

import pytest

from futuros.data import ws
from futuros.data.rest import ClienteREST
from futuros.quality import evaluar

pytestmark = [pytest.mark.red,
              pytest.mark.skipif(os.environ.get("FUTUROS_PRUEBA_REAL") != "1",
                                 reason="prueba real desactivada (activa con FUTUROS_PRUEBA_REAL=1)")]


@pytest.mark.parametrize("simbolo", ["BTCUSDT", "ETHUSDT"])
def test_rest_real(simbolo):
    with ClienteREST() as c:
        t0 = time.time(); servidor = c.hora_servidor_ms(); t1 = time.time()
        desfase = servidor - int((t0 + t1) / 2 * 1000)
        velas, libro, mark = c.velas(simbolo, "1m", 50), c.libro(simbolo, 20), c.mark_price(simbolo)
    r = evaluar(simbolo, velas, libro, mark, int(time.time() * 1000) + desfase, desfase)
    assert len(velas) == 50 and libro.mejor_bid < libro.mejor_ask and mark.mark > 0
    assert r.apto, r.motivos


def test_websocket_real_recibe_mensajes():
    recibidos = []

    async def correr():
        urls = ws.urls_streams(["BTCUSDT"])
        tareas = [asyncio.create_task(ws.escuchar(n, u, recibidos.append, lambda *a: None)) for n, u in urls.items()]
        await asyncio.sleep(8)
        for t in tareas:
            t.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)

    asyncio.run(correr())
    tipos = {type(d).__name__ for d in recibidos}
    assert {"Vela", "Libro", "MarkPrice"} <= tipos, tipos
