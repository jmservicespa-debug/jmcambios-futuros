"""Comando `futuros-riesgo`: pasa las señales por el motor de riesgo y muestra la decisión.

Cuenta SIMULADA (capital = capital de referencia de la config). NO envía órdenes, NO usa llaves.

Ejemplos:
    futuros-riesgo                    # señales reales de ahora -> decisión del motor
    futuros-riesgo --ejemplo          # además, una señal HIPOTÉTICA LONG y SHORT por símbolo para ver el cálculo
    futuros-riesgo --ejemplo --pnl-dia -15   # simula que hoy ya perdiste 15 USDT
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from futuros.config import load
from futuros.data.rest import ClienteREST, ErrorDatos, IPBloqueada, LimiteBinance
from futuros.features import atr
from futuros.quality import evaluar as evaluar_calidad
from futuros.risk import EstadoCuenta, MotorRiesgo
from futuros.strategy import LONG, SHORT, Senal, evaluar
from futuros.strategy.cli import VELAS_A_PEDIR, cargar_config


def senal_hipotetica(base: Senal, direccion: str, atr_valor: Decimal, stop_atr: Decimal,
                     objetivo_atr: Decimal) -> Senal:
    signo = 1 if direccion == LONG else -1
    p = base.precio_ref
    return replace(base, direccion=direccion, stop=p - signo * stop_atr * atr_valor,
                   objetivo=p + signo * objetivo_atr * atr_valor, motivos=["HIPOTÉTICA (solo para ver el cálculo)"])


def mostrar(titulo: str, decision) -> None:
    print(f"    {titulo}")
    if decision.aprobada:
        o = decision.orden
        print(f"      => APROBADA por el motor (propuesta, NO se envía): {o.direccion} {o.lado} {o.cantidad} "
              f"a ~{o.precio_ref}")
        print(f"         stop {o.stop} | objetivo {o.objetivo} | nocional {o.nocional_usdt:.2f} USDT | "
              f"apalancamiento {o.apalancamiento}x | margen {o.margen_usdt:.2f} USDT")
        print(f"         pérdida máx. si salta el stop {o.perdida_max_usdt:.2f} USDT | comisiones est. "
              f"{o.comisiones_usdt:.2f} | ganancia neta est. en el objetivo {o.ganancia_neta_usdt:.2f} USDT")
    else:
        print("      => RECHAZADA:")
        for m in decision.rechazos:
            print(f"         - {m}")


def main(argv: list[str] | None = None, cliente: ClienteREST | None = None) -> int:
    p = argparse.ArgumentParser(prog="futuros-riesgo", description="Decisiones del motor de riesgo (sin órdenes).")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--ejemplo", action="store_true", help="agrega señales hipotéticas LONG y SHORT para ver el cálculo")
    p.add_argument("--pnl-dia", default="0", help="resultado simulado de hoy en USDT (ej. -15)")
    a = p.parse_args(argv)
    try:
        cfg = load(a.config)
        est_cfg, _ = cargar_config(a.config)
        pnl = Decimal(a.pnl_dia)
    except (ValueError, ValidationError, InvalidOperation, FileNotFoundError) as e:
        p.error(f"configuración o parámetro inválido: {e}")
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")

    motor = MotorRiesgo(cfg, est_cfg.comision_pct, est_cfg.comision_maker_pct)
    cuenta = EstadoCuenta(cfg.capital_referencia_usdt, pnl)
    print("=== JM Cambios Futuros - Fase 4: motor de riesgo ===")
    print("Cuenta SIMULADA. NO se envía ninguna orden y NO es una recomendación de inversión.")
    print(f"Capital {cfg.capital_referencia_usdt} USDT | riesgo {cfg.riesgo_por_operacion_pct} %/operación | "
          f"apalancamiento máx. {motor.apalancamiento_max}x | pérdida diaria máx. {cfg.perdida_diaria_max_pct} % | "
          f"resultado de hoy (simulado) {pnl} USDT")
    propio = cliente is None
    cliente = cliente or ClienteREST()
    try:
        reglas = cliente.reglas(cfg.mercados)
        t0 = time.time()
        servidor = cliente.hora_servidor_ms()
        desfase = servidor - int((t0 + time.time()) / 2 * 1000)
        for s in cfg.mercados:
            velas = cliente.velas(s, est_cfg.intervalo, VELAS_A_PEDIR)
            libro, mark = cliente.libro(s, 20), cliente.mark_price(s)
            cal = evaluar_calidad(s, velas, libro, mark, int(time.time() * 1000) + desfase, desfase)
            sn = evaluar(s, velas, est_cfg, tuple(cfg.direcciones), libro, cal.apto, tuple(cal.motivos))
            rg = reglas[s]
            print(f"\n  {s} (tick {rg.tick_precio}, paso {rg.paso_cantidad}, mín. {rg.cantidad_min}, "
                  f"nocional mín. {rg.nocional_min} USDT) - datos {'APTOS' if cal.apto else 'NO APTOS'}")
            mostrar(f"Señal actual: {sn.direccion}" + (f" ({sn.motivos[0]})" if sn.motivos else ""),
                    motor.evaluar(sn, rg, cuenta, cal.apto, tuple(cal.motivos)))
            if a.ejemplo:
                cerradas = [v for v in velas if v.cerrada]
                a_val = atr(cerradas, est_cfg.atr_periodo)[-1] if cerradas else None
                if a_val is None or sn.precio_ref is None:
                    print("    (no hay velas suficientes para el ejemplo)")
                    continue
                for d in (LONG, SHORT):
                    h = senal_hipotetica(sn, d, a_val, est_cfg.stop_atr, est_cfg.objetivo_atr)
                    mostrar(f"Ejemplo HIPOTÉTICO {d}: entrada {h.precio_ref}, stop {h.stop:.2f}, objetivo {h.objetivo:.2f}",
                            motor.evaluar(h, rg, cuenta, cal.apto, tuple(cal.motivos)))
        return 0
    except KeyboardInterrupt:
        print("\nCortado por ti (Ctrl+C).")
        return 0
    except (IPBloqueada, LimiteBinance) as e:
        print(f"\nERROR: Binance pidió esperar. {e}.", file=sys.stderr)
        return 2
    except ErrorDatos as e:
        print(f"\nERROR al pedir datos: {e}", file=sys.stderr)
        return 1
    finally:
        if propio:
            cliente.close()


if __name__ == "__main__":
    raise SystemExit(main())
