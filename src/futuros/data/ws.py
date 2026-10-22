"""WebSocket público de solo lectura (sin llaves).

Binance separa las rutas por tipo de dato:
- /market : velas (<simbolo>@kline_<intervalo>) y mark price (<simbolo>@markPrice@1s)
- /public : libro parcial (<simbolo>@depth<niveles>@500ms)
Se usa el modo combinado /stream?streams=a/b/c, que envuelve cada mensaje como
{"stream": "...", "data": {...}}.

Una conexión dura como máximo 24 h según Binance; aquí se renueva antes (23 h).
El servidor envía ping y la librería websockets responde pong automáticamente.
Solo se escucha: no se envía ningún mensaje al servidor.
"""
from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Awaitable, Callable

from futuros.data import endpoints as ep
from futuros.data.modelos import Libro, MarkPrice, Vela
from futuros.data.rest import validar_simbolo

RENOVAR_CADA_S = 23 * 3600
ESPERA_MAX_RECONEXION_S = 30


def urls_streams(simbolos: list[str], intervalo: str = "1m", niveles_libro: int = 20) -> dict[str, str]:
    if intervalo not in ep.INTERVALOS_MS:
        raise ValueError(f"intervalo no soportado: {intervalo}")
    if niveles_libro not in (5, 10, 20):
        raise ValueError("el libro parcial por WebSocket admite 5, 10 o 20 niveles")
    ss = [validar_simbolo(s).lower() for s in simbolos]
    market = [f"{s}@kline_{intervalo}" for s in ss] + [f"{s}@markPrice@1s" for s in ss]
    public = [f"{s}@depth{niveles_libro}@500ms" for s in ss]
    return {
        "market": f"{ep.WS_MARKET}/stream?streams=" + "/".join(market),
        "public": f"{ep.WS_PUBLIC}/stream?streams=" + "/".join(public),
    }


def parsear_mensaje(raw: str | bytes) -> Vela | Libro | MarkPrice | None:
    """Convierte un mensaje del stream combinado en un objeto. Devuelve None si no se reconoce."""
    msg = json.loads(raw)
    d = msg.get("data", msg)
    tipo = d.get("e")
    if tipo == "kline":
        k = d["k"]
        return Vela(k["s"], k["i"], int(k["t"]), int(k["T"]), Decimal(k["o"]), Decimal(k["h"]),
                    Decimal(k["l"]), Decimal(k["c"]), Decimal(k["v"]), cerrada=bool(k["x"]))
    if tipo == "markPriceUpdate":
        return MarkPrice(d["s"], int(d["E"]), Decimal(d["p"]), Decimal(d["i"]), Decimal(d["r"]), int(d["T"]))
    if tipo == "depthUpdate":
        return Libro(d["s"], int(d["E"]), int(d["u"]),
                     [(Decimal(p), Decimal(q)) for p, q in d["b"]],
                     [(Decimal(p), Decimal(q)) for p, q in d["a"]])
    return None


def _conectar_por_defecto(url: str):
    from websockets.asyncio.client import connect
    return connect(url, open_timeout=10, ping_interval=20, ping_timeout=20, max_queue=256)


async def escuchar(nombre: str, url: str,
                   al_recibir: Callable[[object], None],
                   al_cambiar_estado: Callable[[str, bool, str], None],
                   conectar: Callable = _conectar_por_defecto,
                   reintentos_max: int | None = None,
                   dormir: Callable[[float], Awaitable] = asyncio.sleep,
                   reloj: Callable[[], float] = time.monotonic) -> None:
    """Escucha un stream combinado y reconecta con espera creciente si se cae.

    al_cambiar_estado(nombre, conectado, motivo) avisa de conexiones y desconexiones
    para que el módulo de calidad marque los datos como no aptos mientras dure el corte.
    """
    intentos, espera = 0, 1.0
    while reintentos_max is None or intentos <= reintentos_max:
        intentos += 1
        motivo = "conexión cerrada por el servidor"
        try:
            async with conectar(url) as ws:
                al_cambiar_estado(nombre, True, "conectado")
                espera, inicio = 1.0, reloj()
                async for raw in ws:
                    dato = parsear_mensaje(raw)
                    if dato is not None:
                        al_recibir(dato)
                    if reloj() - inicio > RENOVAR_CADA_S:
                        motivo = "renovación programada (límite de 24 h de Binance)"
                        break
        except asyncio.CancelledError:
            al_cambiar_estado(nombre, False, "detenido")
            raise
        except Exception as e:  # red caída, DNS, cierre inesperado, JSON inválido…
            motivo = f"{type(e).__name__}: {e}"
        al_cambiar_estado(nombre, False, motivo)
        if reintentos_max is not None and intentos > reintentos_max:
            break
        await dormir(espera)
        espera = min(espera * 2, ESPERA_MAX_RECONEXION_S)
