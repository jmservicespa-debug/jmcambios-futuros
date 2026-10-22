"""Comando `futuros-senales`: calcula indicadores y muestra la señal de la estrategia.

Solo lectura y solo señales: NO envía órdenes, NO usa llaves y NO es una recomendación de inversión.

Ejemplos:
    futuros-senales                 # una pasada para BTCUSDT y ETHUSDT
    futuros-senales --minutos 30    # repite cada minuto durante 30 minutos
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml
from pydantic import ValidationError

from futuros.data import almacen as alm
from futuros.data.rest import ClienteREST, ErrorDatos, IPBloqueada, LimiteBinance, validar_simbolo
from futuros.quality import evaluar as evaluar_calidad
from futuros.strategy import NINGUNA, EstrategiaConfig, evaluar

SIMBOLOS = ["BTCUSDT", "ETHUSDT"]
VELAS_A_PEDIR = 200


def cargar_config(ruta: str | Path) -> tuple[EstrategiaConfig, tuple[str, ...]]:
    """Lee la sección `estrategia` y `direcciones` de config/default.yaml (si no existe, usa valores por defecto)."""
    ruta = Path(ruta)
    if not ruta.exists():
        return EstrategiaConfig(), ("LONG", "SHORT")
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    direcciones = tuple(datos.get("direcciones") or ("LONG", "SHORT"))
    if any(d not in ("LONG", "SHORT") for d in direcciones):
        raise ValueError("direcciones permitidas: LONG y/o SHORT")
    return EstrategiaConfig(**(datos.get("estrategia") or {})), direcciones


def _fmt(x, dec=2) -> str:
    return "?" if x is None else f"{x:.{dec}f}"


def una_pasada(cliente: ClienteREST, simbolos: list[str], cfg: EstrategiaConfig, direcciones: tuple[str, ...],
               almacen: alm.Almacen, reloj=None) -> list:
    reloj = reloj or time.time
    t0 = reloj()
    servidor = cliente.hora_servidor_ms()
    desfase = servidor - int((t0 + reloj()) / 2 * 1000)
    senales = []
    print(f"\n[{time.strftime('%H:%M:%S')}] velas de {cfg.intervalo}")
    for s in simbolos:
        velas = cliente.velas(s, cfg.intervalo, VELAS_A_PEDIR)
        libro = cliente.libro(s, 20)
        mark = cliente.mark_price(s)
        calidad = evaluar_calidad(s, velas, libro, mark, int(reloj() * 1000) + desfase, desfase)
        almacen.guardar_velas(velas)
        sn = evaluar(s, velas, cfg, direcciones, libro, calidad.apto, tuple(calidad.motivos))
        almacen.guardar_senal(sn, cfg.intervalo)
        senales.append(sn)
        ind = sn.indicadores
        print(f"  {s:<8} precio {_fmt(sn.precio_ref)} | EMA{cfg.ema_rapida} {_fmt(ind.get('ema_rapida'))} | "
              f"EMA{cfg.ema_lenta} {_fmt(ind.get('ema_lenta'))} | VWAP {_fmt(ind.get('vwap'))} | "
              f"ATR {_fmt(ind.get('atr'))}")
        if sn.direccion == NINGUNA:
            print("    => SIN SEÑAL")
        else:
            print(f"    => SEÑAL {sn.direccion}: referencia {_fmt(sn.precio_ref)}, "
                  f"stop {_fmt(sn.stop)}, objetivo {_fmt(sn.objetivo)}")
        for m in sn.motivos:
            print(f"       - {m}")
    return senales


def main(argv: list[str] | None = None, cliente: ClienteREST | None = None, dormir=time.sleep) -> int:
    p = argparse.ArgumentParser(prog="futuros-senales",
                                description="Ver señales de la estrategia (solo lectura, sin órdenes).")
    p.add_argument("--simbolos", nargs="+", default=SIMBOLOS, help="por defecto: BTCUSDT ETHUSDT")
    p.add_argument("--minutos", type=int, default=0, help="repetir cada minuto durante N minutos (0 = una vez)")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--db", default=str(alm.RUTA_POR_DEFECTO))
    a = p.parse_args(argv)
    if not 0 <= a.minutos <= 24 * 60:
        p.error("--minutos debe estar entre 0 y 1440")
    try:
        simbolos = [validar_simbolo(s) for s in a.simbolos]
        cfg, direcciones = cargar_config(a.config)
    except (ValueError, ValidationError) as e:
        p.error(f"configuración inválida: {e}")
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")

    print("=== JM Cambios Futuros - Fase 3: señales de la estrategia ===")
    print("Solo señales para estudiar. NO se envía ninguna orden y NO es una recomendación de inversión.")
    print(f"Direcciones permitidas: {', '.join(direcciones)} | intervalo: {cfg.intervalo}")
    almacen = alm.Almacen(a.db)
    propio = cliente is None
    cliente = cliente or ClienteREST()
    try:
        pasadas = max(1, a.minutos)
        for i in range(pasadas):
            una_pasada(cliente, simbolos, cfg, direcciones, almacen)
            if i < pasadas - 1:
                dormir(60)
        print(f"\nSeñales guardadas en {Path(a.db).resolve()} (total: {almacen.contar('senales')})")
        return 0
    except KeyboardInterrupt:
        print("\nCortado por ti (Ctrl+C).")
        return 0
    except IPBloqueada as e:
        print(f"\nERROR: Binance bloqueó temporalmente tu IP. {e}. No reintentes ahora.", file=sys.stderr)
        return 2
    except LimiteBinance as e:
        print(f"\nERROR: Binance pidió bajar el ritmo. {e}.", file=sys.stderr)
        return 2
    except ErrorDatos as e:
        print(f"\nERROR al pedir datos: {e}", file=sys.stderr)
        return 1
    finally:
        almacen.close()
        if propio:
            cliente.close()


if __name__ == "__main__":
    raise SystemExit(main())
