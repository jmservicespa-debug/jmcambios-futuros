"""Descarga de velas históricas (solo lectura) a SQLite, por bloques y respetando el peso.

- Pide de a 1000 velas (peso 5 en /fapi/v1/klines) avanzando con startTime.
- Si se alcanza nuestro tope propio de peso por minuto, espera al minuto siguiente.
- Si Binance responde 429/418, se detiene (no reintenta): el error sube a quien llamó.
- Retoma donde quedó: si ya hay velas guardadas, sigue desde la última.
"""
from __future__ import annotations

import time
from typing import Callable

from futuros.data.almacen import Almacen
from futuros.data.endpoints import INTERVALOS_MS
from futuros.data.rest import ClienteREST, PresupuestoPesoAgotado

BLOQUE = 1000
DIA_MS = 86_400_000


def huecos(velas, intervalo: str) -> list[tuple[int, int]]:
    """Tramos faltantes (desde_ms, hasta_ms) en una serie ordenada de velas."""
    paso = INTERVALOS_MS[intervalo]
    return [(a.apertura_ms + paso, b.apertura_ms - paso)
            for a, b in zip(velas, velas[1:]) if b.apertura_ms - a.apertura_ms > paso]


def descargar(cliente: ClienteREST, almacen: Almacen, simbolo: str, intervalo: str, dias: int,
              ahora_ms: int | None = None, dormir: Callable[[float], None] = time.sleep,
              avisar: Callable[[str], None] = print) -> int:
    """Descarga `dias` días de velas cerradas. Devuelve cuántas velas nuevas se guardaron."""
    if not 1 <= dias <= 1095:
        raise ValueError("dias debe estar entre 1 y 1095")
    paso = INTERVALOS_MS[intervalo]
    ahora_ms = ahora_ms if ahora_ms is not None else int(time.time() * 1000)
    inicio = (ahora_ms - dias * DIA_MS) // paso * paso
    ya = almacen.leer_velas(simbolo, intervalo, inicio)
    if ya:
        inicio = max(inicio, ya[-1].apertura_ms + paso)
    total = 0
    while inicio < ahora_ms - paso:
        try:
            bloque = cliente.velas(simbolo, intervalo, BLOQUE, inicio_ms=inicio)
        except PresupuestoPesoAgotado:
            espera = 61 - (time.time() % 60)
            avisar(f"  pausa de {espera:.0f} s para respetar el límite de peso...")
            dormir(espera)
            continue
        cerradas = [v for v in bloque if v.cierre_ms < ahora_ms]
        if not cerradas:
            break
        almacen.guardar_velas(cerradas)
        total += len(cerradas)
        avisar(f"  {simbolo}: {total} velas nuevas (hasta {time.strftime('%Y-%m-%d %H:%M', time.gmtime(cerradas[-1].apertura_ms / 1000))} UTC)")
        if len(bloque) < BLOQUE:
            break
        inicio = cerradas[-1].apertura_ms + paso
    return total
