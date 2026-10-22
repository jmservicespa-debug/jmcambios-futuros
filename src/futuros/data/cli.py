"""Comando `futuros-datos`: muestra en consola que llegan datos reales de Binance.

Solo lectura: no usa llaves API y no envía órdenes.

Ejemplos:
    futuros-datos                    # REST + 60 s de WebSocket para BTCUSDT y ETHUSDT
    futuros-datos --segundos 120
    futuros-datos --solo-rest
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from futuros.data import almacen as alm
from futuros.data import ws
from futuros.data.modelos import Libro, MarkPrice, Vela
from futuros.data.rest import ClienteREST, ErrorDatos, IPBloqueada, LimiteBinance, validar_simbolo
from futuros.quality import MonitorConexion, evaluar

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]
GUARDAR_CADA_MS = 5_000
MAX_VELAS_EN_MEMORIA = 200


class Estado:
    """Últimos datos por símbolo, más el desfase de reloj con Binance."""

    def __init__(self, simbolos: list[str], desfase_ms: int = 0, reloj=None):
        self.simbolos = simbolos
        self.desfase_ms = desfase_ms
        self._reloj = reloj or time.time
        self.velas: dict[str, list[Vela]] = {s: [] for s in simbolos}
        self.libro: dict[str, Libro | None] = {s: None for s in simbolos}
        self.mark: dict[str, MarkPrice | None] = {s: None for s in simbolos}
        self.mensajes = 0

    def ahora_ms(self) -> int:
        return int(self._reloj() * 1000) + self.desfase_ms

    def agregar_vela(self, v: Vela) -> None:
        lista = self.velas.setdefault(v.simbolo, [])
        if lista and lista[-1].apertura_ms == v.apertura_ms:
            lista[-1] = v
        elif not lista or v.apertura_ms > lista[-1].apertura_ms:
            lista.append(v)
            del lista[:-MAX_VELAS_EN_MEMORIA]


def _fmt_resultado(r) -> str:
    if r.apto:
        return "APTO para operar"
    return "NO APTO para operar:" + "".join(f"\n      - {m}" for m in r.motivos)


def _linea(est: Estado, s: str, monitor: MonitorConexion | None) -> tuple[str, object]:
    r = evaluar(s, est.velas[s], est.libro[s], est.mark[s], est.ahora_ms(), est.desfase_ms, monitor)
    v = est.velas[s][-1] if est.velas[s] else None
    lb, mp = est.libro[s], est.mark[s]
    partes = [f"{s:<8}",
              f"último {v.cierre}" if v else "último ?",
              f"mark {mp.mark:.2f}" if mp else "mark ?",
              f"funding {mp.funding * 100:.4f} %" if mp else "funding ?",
              f"compra {lb.mejor_bid} / venta {lb.mejor_ask}" if lb else "libro ?"]
    return " | ".join(partes) + f"\n    => {_fmt_resultado(r)}", r


def descargar_rest(cliente: ClienteREST, simbolos: list[str], almacen: alm.Almacen, reloj=None) -> Estado:
    reloj = reloj or time.time
    t0 = reloj()
    servidor = cliente.hora_servidor_ms()
    t1 = reloj()
    est = Estado(simbolos, servidor - int((t0 + t1) / 2 * 1000), reloj)
    print(f"Hora de Binance recibida. Desfase de tu reloj: {est.desfase_ms / 1000:+.2f} s")
    for s in simbolos:
        velas = cliente.velas(s, "1m", 100)
        est.velas[s] = velas
        est.libro[s] = cliente.libro(s, 20)
        est.mark[s] = cliente.mark_price(s)
        funding = cliente.historial_funding(s, 3)
        almacen.guardar_velas(velas)
        almacen.guardar_libro(est.libro[s])
        almacen.guardar_mark(est.mark[s])
        print(f"  {s}: {len(velas)} velas de 1m, libro con {len(est.libro[s].bids)} niveles, "
              f"últimos funding: {', '.join(f'{f.tasa * 100:.4f} %' for f in funding) or 'sin datos'}")
    print(f"Peso usado en el último minuto (según Binance): {cliente.peso_usado}")
    print("\nCalidad de los datos REST:")
    for s in simbolos:
        texto, r = _linea(est, s, None)
        almacen.guardar_calidad(s, est.ahora_ms(), r.apto, r.motivos)
        print("  " + texto)
    return est


async def seguir_ws(est: Estado, almacen: alm.Almacen, segundos: int, conectar=None,
                    cada_s: float = 5.0) -> list[tuple[str, object]]:
    """Escucha el WebSocket y devuelve el resumen final (calculado antes de cerrar las conexiones)."""
    monitor = MonitorConexion()
    ultimo_guardado: dict[tuple[str, str], int] = {}
    tipo_de = {Vela: "vela", Libro: "libro", MarkPrice: "mark"}

    def al_recibir(dato) -> None:
        est.mensajes += 1
        ahora = est.ahora_ms()
        tipo = tipo_de[type(dato)]
        monitor.mensaje(dato.simbolo, tipo, ahora)
        if isinstance(dato, Vela):
            est.agregar_vela(dato)
            if dato.cerrada:
                almacen.guardar_velas([dato])
            return
        if isinstance(dato, Libro):
            est.libro[dato.simbolo] = dato
        else:
            est.mark[dato.simbolo] = dato
        clave = (dato.simbolo, tipo)
        if ahora - ultimo_guardado.get(clave, 0) >= GUARDAR_CADA_MS:
            ultimo_guardado[clave] = ahora
            (almacen.guardar_libro if tipo == "libro" else almacen.guardar_mark)(dato)

    def al_cambiar(nombre: str, conectado: bool, motivo: str) -> None:
        monitor.cambio_estado(nombre, conectado, motivo)
        print(f"  [WebSocket {nombre}] {'conectado' if conectado else 'DESCONECTADO: ' + motivo}")

    urls = ws.urls_streams(est.simbolos)
    extra = {"conectar": conectar} if conectar else {}
    tareas = [asyncio.create_task(ws.escuchar(n, u, al_recibir, al_cambiar, **extra)) for n, u in urls.items()]

    async def informar():
        while True:
            await asyncio.sleep(cada_s)
            print(f"\n[{time.strftime('%H:%M:%S')}] mensajes recibidos: {est.mensajes}")
            for s in est.simbolos:
                print("  " + _linea(est, s, monitor)[0])

    tareas.append(asyncio.create_task(informar()))
    try:
        await asyncio.sleep(segundos)
        return [_linea(est, s, monitor) for s in est.simbolos]
    finally:
        for t in tareas:
            t.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)


def main(argv: list[str] | None = None, cliente: ClienteREST | None = None, conectar=None) -> int:
    p = argparse.ArgumentParser(prog="futuros-datos",
                                description="Ver datos de mercado de Binance Futuros (solo lectura, sin llaves).")
    p.add_argument("--simbolos", nargs="+", default=SIMBOLOS, help="por defecto: BTCUSDT ETHUSDT")
    p.add_argument("--segundos", type=int, default=60, help="tiempo escuchando el WebSocket (por defecto 60)")
    p.add_argument("--solo-rest", action="store_true", help="solo la descarga REST, sin WebSocket")
    p.add_argument("--db", default=str(alm.RUTA_POR_DEFECTO), help="archivo SQLite (por defecto data/mercado.sqlite)")
    a = p.parse_args(argv)
    if not 1 <= a.segundos <= 24 * 3600:
        p.error("--segundos debe estar entre 1 y 86400")
    try:
        simbolos = [validar_simbolo(s) for s in a.simbolos]
    except ValueError as e:
        p.error(str(e))
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")  # consolas de Windows con otra codificación

    print("=== JM Cambios Futuros - Fase 2: datos SOLO LECTURA ===")
    print("Sin llaves API. Sin órdenes. Solo se leen datos públicos de Binance Futuros USD-M.\n")
    almacen = alm.Almacen(a.db)
    propio = cliente is None
    cliente = cliente or ClienteREST()
    try:
        est = descargar_rest(cliente, simbolos, almacen)
        if not a.solo_rest:
            print(f"\nEscuchando WebSocket durante {a.segundos} s (Ctrl+C para cortar antes)...")
            try:
                final = asyncio.run(seguir_ws(est, almacen, a.segundos, conectar))
            except KeyboardInterrupt:
                print("\nCortado por ti (Ctrl+C).")
                final = [_linea(est, s, None) for s in simbolos]
            print("\n=== Resumen final ===")
            print(f"Mensajes WebSocket recibidos: {est.mensajes}")
            for s, (texto, r) in zip(simbolos, final):
                almacen.guardar_calidad(s, est.ahora_ms(), r.apto, r.motivos)
                print("  " + texto)
        print(f"\nDatos guardados en {Path(a.db).resolve()} "
              f"(velas: {almacen.contar('velas')}, libros: {almacen.contar('libros')}, "
              f"mark price: {almacen.contar('mark_price')})")
        return 0
    except IPBloqueada as e:
        print(f"\nERROR: Binance bloqueó temporalmente tu IP por exceso de solicitudes. {e}. "
              "No reintentes ahora; espera ese tiempo.", file=sys.stderr)
        return 2
    except LimiteBinance as e:
        print(f"\nERROR: Binance pidió bajar el ritmo. {e}.", file=sys.stderr)
        return 2
    except ErrorDatos as e:
        print(f"\nERROR al pedir datos: {e}\nRevisa tu internet o si un firewall/antivirus bloquea fapi.binance.com.",
              file=sys.stderr)
        return 1
    finally:
        almacen.close()
        if propio:
            cliente.close()


if __name__ == "__main__":
    raise SystemExit(main())
