"""Comandos de la Fase 5 (solo lectura, sin órdenes):

    futuros-historico --dias 90        # descarga velas históricas a data/mercado.sqlite
    futuros-backtest                   # simula con lo descargado y escribe el informe en reports/
    futuros-backtest --objetivo-neto 0.5   # "¿y si...?": cambia el objetivo neto SOLO en esta simulación
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from futuros.backtest import historico, informe
from futuros.backtest.simulador import ParametrosBacktest, correr
from futuros.config import load
from futuros.data import almacen as alm
from futuros.data.rest import ClienteREST, ErrorDatos, IPBloqueada, LimiteBinance
from futuros.strategy.cli import cargar_config


def _consola() -> None:
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")


def main_historico(argv: list[str] | None = None, cliente: ClienteREST | None = None, dormir=time.sleep) -> int:
    p = argparse.ArgumentParser(prog="futuros-historico", description="Descarga velas históricas (solo lectura).")
    p.add_argument("--dias", type=int, default=90)
    p.add_argument("--intervalo", default=None, help="ej. 15m (por defecto el de la configuración)")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--db", default=str(alm.RUTA_POR_DEFECTO))
    a = p.parse_args(argv)
    try:
        cfg = load(a.config)
        est, _ = cargar_config(a.config)
        if a.intervalo:
            est = est.model_validate({**est.model_dump(), "intervalo": a.intervalo})
    except (ValueError, ValidationError, FileNotFoundError) as e:
        p.error(f"configuración inválida: {e}")
    if not 1 <= a.dias <= 1095:
        p.error("--dias debe estar entre 1 y 1095")
    _consola()
    print(f"=== Descarga de {a.dias} días de velas de {est.intervalo} (solo lectura) ===")
    almacen = alm.Almacen(a.db)
    propio = cliente is None
    cliente = cliente or ClienteREST()
    try:
        for s in cfg.mercados:
            n = historico.descargar(cliente, almacen, s, est.intervalo, a.dias, dormir=dormir)
            velas = almacen.leer_velas(s, est.intervalo, int(time.time() * 1000) - a.dias * historico.DIA_MS)
            hs = historico.huecos(velas, est.intervalo)
            print(f"{s}: {n} velas nuevas, {len(velas)} en total para el periodo"
                  + (f", {len(hs)} hueco(s) en la serie (Binance pudo estar en mantención)" if hs else ", sin huecos"))
        print(f"\nGuardado en {Path(a.db).resolve()}")
        return 0
    except (IPBloqueada, LimiteBinance) as e:
        print(f"\nERROR: Binance pidió esperar. {e}. Lo descargado quedó guardado; vuelve a correr más tarde y "
              "seguirá donde quedó.", file=sys.stderr)
        return 2
    except ErrorDatos as e:
        print(f"\nERROR al pedir datos: {e}", file=sys.stderr)
        return 1
    finally:
        almacen.close()
        if propio:
            cliente.close()


def main_backtest(argv: list[str] | None = None, cliente: ClienteREST | None = None) -> int:
    p = argparse.ArgumentParser(prog="futuros-backtest", description="Backtest con velas descargadas (sin órdenes).")
    p.add_argument("--dias", type=int, default=90)
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--db", default=str(alm.RUTA_POR_DEFECTO))
    p.add_argument("--reportes", default="reports")
    p.add_argument("--deslizamiento", default="0.02", help="%% en contra por ejecución a mercado (por defecto 0.02)")
    p.add_argument("--objetivo-neto", default=None, help="cambia el objetivo neto SOLO en esta simulación")
    p.add_argument("--comision", default=None, help="cambia la comisión taker (%%) SOLO en esta simulación")
    p.add_argument("--intervalo", default=None, help="ej. 15m: prueba otro intervalo SOLO en esta simulación")
    p.add_argument("--objetivo-atr", default=None, help="ej. 3: objetivo a N ATR SOLO en esta simulación")
    a = p.parse_args(argv)
    try:
        cfg = load(a.config)
        est, _ = cargar_config(a.config)
        params = ParametrosBacktest(deslizamiento_pct=Decimal(a.deslizamiento))
        cambios = []
        if a.objetivo_neto is not None:
            cfg = cfg.model_validate({**cfg.model_dump(), "objetivo_neto_por_operacion_usdt": Decimal(a.objetivo_neto)})
            cambios.append(f"objetivo neto {a.objetivo_neto} USDT")
        if a.comision is not None:
            est = est.model_validate({**est.model_dump(), "comision_pct": Decimal(a.comision)})
            cambios.append(f"comisión taker {a.comision} %")
        if a.intervalo is not None:
            est = est.model_validate({**est.model_dump(), "intervalo": a.intervalo})
            cambios.append(f"velas de {a.intervalo}")
        if a.objetivo_atr is not None:
            est = est.model_validate({**est.model_dump(), "objetivo_atr": Decimal(a.objetivo_atr)})
            cambios.append(f"objetivo a {a.objetivo_atr} ATR")
    except (ValueError, ValidationError, InvalidOperation, FileNotFoundError) as e:
        p.error(f"configuración o parámetro inválido: {e}")
    _consola()
    almacen = alm.Almacen(a.db)
    desde = int(time.time() * 1000) - a.dias * historico.DIA_MS
    series = {s: almacen.leer_velas(s, est.intervalo, desde) for s in cfg.mercados}
    almacen.close()
    faltan = [s for s, v in series.items() if len(v) < params.ventana + 10]
    if faltan:
        extra = f" --intervalo {a.intervalo}" if a.intervalo else ""
        print(f"No hay velas suficientes de {', '.join(faltan)}. Primero corre: futuros-historico --dias {a.dias}{extra}",
              file=sys.stderr)
        return 1
    propio = cliente is None
    cliente = cliente or ClienteREST()
    try:
        reglas = cliente.reglas(cfg.mercados)
    except ErrorDatos as e:
        print(f"ERROR al pedir las reglas de los símbolos a Binance: {e}", file=sys.stderr)
        return 1
    finally:
        if propio:
            cliente.close()

    print(f"=== Backtest: {sum(len(v) for v in series.values())} velas de {est.intervalo} "
          f"({', '.join(cfg.mercados)}) – puede tardar unos minutos ===")
    if cambios:
        print("Simulación \"¿y si...?\" con: " + ", ".join(cambios) + " (tu config/default.yaml NO cambia)")
    t0 = time.time()
    res = correr(series, cfg, est, reglas, params)
    notas = [f"entrada en la apertura siguiente con {params.deslizamiento_pct} % de deslizamiento",
             f"comisión taker {est.comision_pct} % en entrada y stop, maker {est.comision_maker_pct} % en el objetivo",
             "stop antes que objetivo si ambos ocurren en la misma vela",
             "sin filtro de spread (no hay libro histórico) y sin funding",
             f"objetivo neto mínimo {cfg.objetivo_neto_por_operacion_usdt} USDT, riesgo {cfg.riesgo_por_operacion_pct} %, "
             f"apalancamiento máx. {cfg.apalancamiento_max}x"] + (["cambios solo para esta simulación: " + ", ".join(cambios)]
                                                                    if cambios else [])
    txt = informe.texto(res, cfg.mercados, est.intervalo, notas)
    print(txt)
    carpeta = Path(a.reportes)
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"backtest-{time.strftime('%Y%m%d-%H%M%S')}.md"
    archivo.write_text(txt, encoding="utf-8")
    print(f"Informe guardado en {archivo.resolve()} ({time.time() - t0:.0f} s)")
    return 0
