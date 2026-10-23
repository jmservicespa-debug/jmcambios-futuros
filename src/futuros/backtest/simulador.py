"""Backtest vela por vela: la estrategia propone, el MOTOR DE RIESGO decide, y se simula el resultado.

Supuestos (conservadores y escritos aquí para que el informe sea honesto):
- La estrategia ve las mismas 199 velas cerradas que ve en vivo, y solo en el cierre de cada vela.
- Una orden aprobada entra en la APERTURA de la vela siguiente, con deslizamiento en contra.
- Comisión taker en la entrada y en la salida (no se asume comisión maker más barata).
- Si en una misma vela se tocan el stop y el objetivo, se asume que primero se tocó el STOP.
- Si la vela abre más allá del stop (salto), se sale en la apertura, que es un precio peor que el stop.
- Las salidas por stop pagan deslizamiento; las del objetivo no, porque se asume una orden límite.
- Sin libro histórico, el filtro de spread no se aplica. El funding no se cobra (las operaciones duran poco),
  pero puede sumar costos en operaciones largas.
- Si la ventana tiene huecos, los datos se consideran NO APTOS para ese momento.
- Una sola cuenta compartida por todos los símbolos; la pérdida diaria se reinicia a las 00:00 UTC.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from futuros.config import Config
from futuros.data.endpoints import INTERVALOS_MS
from futuros.data.modelos import ReglasSimbolo, Vela
from futuros.risk import EstadoCuenta, MotorRiesgo, OrdenPropuesta, PosicionAbierta
from futuros.strategy import LONG, SHORT, EstrategiaConfig, Senal
from futuros.strategy import evaluar as evaluar_estrategia

DIA_MS = 86_400_000
CIEN = Decimal(100)


@dataclass(frozen=True)
class ParametrosBacktest:
    deslizamiento_pct: Decimal = Decimal("0.02")   # por ejecución a mercado, siempre en contra
    ventana: int = 199                             # velas cerradas que ve la estrategia (igual que en vivo)


@dataclass(frozen=True)
class Operacion:
    simbolo: str
    direccion: str
    entrada_ms: int
    salida_ms: int
    precio_entrada: Decimal
    precio_salida: Decimal
    cantidad: Decimal
    motivo_salida: str          # objetivo | stop | salto sobre el stop | fin de datos
    bruto: Decimal
    comisiones: Decimal
    neto: Decimal


@dataclass
class ResultadoBacktest:
    capital_inicial: Decimal
    capital_final: Decimal
    operaciones: list[Operacion] = field(default_factory=list)
    senales: int = 0
    aprobadas: int = 0
    rechazos: Counter = field(default_factory=Counter)
    velas_evaluadas: int = 0
    desde_ms: int = 0
    hasta_ms: int = 0


def _categoria(motivo: str) -> str:
    """Agrupa los motivos de rechazo (sin cifras) para poder contarlos."""
    for clave in ("ganancia neta estimada", "pérdida diaria", "mínimo del exchange", "liquidación", "datos NO APTOS",
                  "posición abierta", "posición(es) abierta(s)", "no permitida", "lado correcto", "modo real",
                  "límite rígido"):
        if clave in motivo:
            return clave
    return motivo[:60]


def _ventana_con_huecos(velas: list[Vela], paso: int) -> list[int]:
    """prefijo[i] = cantidad de huecos entre velas[0..i]; sirve para saber si una ventana tiene huecos."""
    pref, acum = [0], 0
    for a, b in zip(velas, velas[1:]):
        acum += b.apertura_ms - a.apertura_ms != paso
        pref.append(acum)
    return pref


def correr(series: dict[str, list[Vela]], cfg: Config, est: EstrategiaConfig, reglas: dict[str, ReglasSimbolo],
           p: ParametrosBacktest = ParametrosBacktest(),
           generador: Callable[..., Senal] | None = None) -> ResultadoBacktest:
    motor = MotorRiesgo(cfg, est.comision_pct)
    com = est.comision_pct / CIEN
    desl = p.deslizamiento_pct / CIEN
    paso = INTERVALOS_MS[est.intervalo]
    simbolos = sorted(series)
    velas = {s: sorted((v for v in series[s] if v.cerrada), key=lambda v: v.apertura_ms) for s in simbolos}
    indice = {s: {v.apertura_ms: i for i, v in enumerate(velas[s])} for s in simbolos}
    huecos = {s: _ventana_con_huecos(velas[s], paso) for s in simbolos}
    tiempos = sorted({v.apertura_ms for s in simbolos for v in velas[s]})
    generador = generador or (lambda s, ventana, apto, motivos: evaluar_estrategia(
        s, ventana, est, tuple(cfg.direcciones), None, apto, motivos))

    capital = cfg.capital_referencia_usdt
    res = ResultadoBacktest(capital, capital, desde_ms=tiempos[0] if tiempos else 0,
                            hasta_ms=tiempos[-1] if tiempos else 0)
    pnl_dia, dia = Decimal(0), None
    pendiente: OrdenPropuesta | None = None
    pos: dict | None = None

    def cerrar(v: Vela, precio: Decimal, motivo: str) -> None:
        nonlocal capital, pnl_dia, pos
        signo = 1 if pos["dir"] == LONG else -1
        bruto = (precio - pos["entrada"]) * pos["cant"] * signo
        comisiones = pos["cant"] * (pos["entrada"] + precio) * com
        neto = bruto - comisiones
        capital += neto
        pnl_dia += neto
        res.operaciones.append(Operacion(pos["sim"], pos["dir"], pos["t"], v.apertura_ms, pos["entrada"], precio,
                                         pos["cant"], motivo, bruto, comisiones, neto))
        pos = None

    for t in tiempos:
        if t // DIA_MS != dia:
            dia, pnl_dia = t // DIA_MS, Decimal(0)
        for s in simbolos:
            i = indice[s].get(t)
            if i is None:
                continue
            v = velas[s][i]

            # 1) Entrar si había una orden aprobada esperando esta vela.
            if pendiente is not None and pendiente.simbolo == s:
                o = pendiente
                entrada = v.apertura * (1 + desl) if o.direccion == LONG else v.apertura * (1 - desl)
                pos = dict(sim=s, dir=o.direccion, cant=o.cantidad, entrada=entrada, stop=o.stop,
                           objetivo=o.objetivo, t=v.apertura_ms, nocional=o.cantidad * entrada)
                pendiente = None

            # 2) Gestionar la posición abierta en esta vela (stop primero: supuesto conservador).
            if pos is not None and pos["sim"] == s:
                larga = pos["dir"] == LONG
                stop, obj = pos["stop"], pos["objetivo"]
                salto = v.apertura <= stop if larga else v.apertura >= stop
                toca_stop = v.minimo <= stop if larga else v.maximo >= stop
                toca_obj = v.maximo >= obj if larga else v.minimo <= obj
                if salto:      # también en la vela de entrada: si abre ya pasado el stop, sale de inmediato
                    cerrar(v, v.apertura * (1 - desl) if larga else v.apertura * (1 + desl), "salto sobre el stop")
                elif toca_stop:
                    cerrar(v, stop * (1 - desl) if larga else stop * (1 + desl), "stop")
                elif toca_obj:
                    cerrar(v, obj, "objetivo")

            # 3) Evaluar señal al cierre de la vela (si no hay posición en este símbolo ni orden esperando).
            if pendiente is not None or (pos is not None and pos["sim"] == s) or i + 1 < max(p.ventana, est.velas_minimas):
                continue
            ini = max(0, i - p.ventana + 1)
            apto = huecos[s][i] - huecos[s][ini] == 0
            res.velas_evaluadas += 1
            sn = generador(s, velas[s][ini:i + 1], apto, () if apto else ("hueco en las velas",))
            if sn.direccion not in (LONG, SHORT):
                continue
            res.senales += 1
            abiertas = () if pos is None else (PosicionAbierta(pos["sim"], pos["dir"], pos["nocional"]),)
            d = motor.evaluar(sn, reglas[s], EstadoCuenta(capital, pnl_dia, abiertas), apto)
            if d.aprobada:
                res.aprobadas += 1
                pendiente = d.orden
            else:
                for m in d.rechazos:
                    res.rechazos[_categoria(m)] += 1

    if pos is not None:                       # cerrar lo que quedó abierto al final de los datos
        v = velas[pos["sim"]][-1]
        cerrar(v, v.cierre, "fin de datos")
    res.capital_final = capital
    return res
