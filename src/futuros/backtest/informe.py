"""Métricas e informe del backtest, en español y sin maquillaje."""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from futuros.backtest.simulador import Operacion, ResultadoBacktest

CIEN = Decimal(100)


@dataclass(frozen=True)
class Metricas:
    operaciones: int
    ganadoras: int
    tasa_acierto_pct: Decimal
    bruto: Decimal
    comisiones: Decimal
    neto: Decimal
    promedio_neto: Decimal
    factor_beneficio: Decimal | None     # ganancias netas / pérdidas netas (None si no hubo pérdidas)
    caida_max_usdt: Decimal
    caida_max_pct: Decimal
    peor_racha: int                      # operaciones perdedoras seguidas
    acierto_para_empatar_pct: Decimal | None   # pérdida media / (ganancia media + pérdida media)


def calcular(ops: list[Operacion], capital_inicial: Decimal) -> Metricas:
    cero = Decimal(0)
    n = len(ops)
    gan = [o.neto for o in ops if o.neto > 0]
    per = [o.neto for o in ops if o.neto <= 0]
    capital = pico = capital_inicial
    caida = caida_pct = cero
    racha = peor = 0
    for o in ops:
        capital += o.neto
        pico = max(pico, capital)
        if pico - capital > caida:
            caida, caida_pct = pico - capital, (pico - capital) / pico * CIEN
        racha = racha + 1 if o.neto <= 0 else 0
        peor = max(peor, racha)
    neto = sum((o.neto for o in ops), cero)
    return Metricas(
        operaciones=n, ganadoras=len(gan), tasa_acierto_pct=Decimal(len(gan)) / n * CIEN if n else cero,
        bruto=sum((o.bruto for o in ops), cero), comisiones=sum((o.comisiones for o in ops), cero), neto=neto,
        promedio_neto=neto / n if n else cero,
        factor_beneficio=(sum(gan, cero) / -sum(per, cero)) if per and sum(per, cero) < 0 else None,
        caida_max_usdt=caida, caida_max_pct=caida_pct, peor_racha=peor,
        acierto_para_empatar_pct=_empate(gan, per))


def _empate(gan: list[Decimal], per: list[Decimal]) -> Decimal | None:
    if not gan or not per:
        return None
    media_g, media_p = sum(gan) / len(gan), -sum(per) / len(per)
    return media_p / (media_g + media_p) * CIEN if media_g + media_p > 0 else None


def dividir(res: ResultadoBacktest, fraccion: Decimal = Decimal("0.7")) -> tuple[list[Operacion], list[Operacion], int]:
    """Separa las operaciones en un primer tramo (70 % del tiempo) y un tramo final (30 %)."""
    corte = res.desde_ms + int((res.hasta_ms - res.desde_ms) * fraccion)
    return [o for o in res.operaciones if o.entrada_ms < corte], [o for o in res.operaciones if o.entrada_ms >= corte], corte


def _fecha(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def _bloque(titulo: str, m: Metricas) -> list[str]:
    fb = f"{m.factor_beneficio:.2f}" if m.factor_beneficio is not None else "sin pérdidas"
    r = [f"### {titulo}",
            f"- Operaciones: {m.operaciones} (ganadoras {m.ganadoras}, {m.tasa_acierto_pct:.1f} %)",
            f"- Resultado bruto: {m.bruto:.2f} USDT | comisiones: {m.comisiones:.2f} USDT | **neto: {m.neto:.2f} USDT**",
            f"- Promedio neto por operación: {m.promedio_neto:.2f} USDT | factor de beneficio: {fb}",
            f"- Caída máxima: {m.caida_max_usdt:.2f} USDT ({m.caida_max_pct:.2f} %) | peor racha perdedora: {m.peor_racha}"]
    if m.acierto_para_empatar_pct is not None:
        r.append(f"- Con estas ganancias y pérdidas medias, hay que acertar el {m.acierto_para_empatar_pct:.1f} % "
                 f"solo para empatar (se acertó el {m.tasa_acierto_pct:.1f} %)")
    return r + [""]


def texto(res: ResultadoBacktest, simbolos: list[str], intervalo: str, notas: list[str]) -> str:
    total = calcular(res.operaciones, res.capital_inicial)
    a, b, corte = dividir(res)
    ret = (res.capital_final - res.capital_inicial) / res.capital_inicial * CIEN
    l = ["# Informe de backtest – JM Cambios Futuros", "",
         "> Simulación con datos históricos. **No garantiza resultados futuros.** No se envió ninguna orden.", "",
         f"- Periodo: {_fecha(res.desde_ms)} a {_fecha(res.hasta_ms)} (UTC) | símbolos: {', '.join(simbolos)} | velas de {intervalo}",
         f"- Capital inicial: {res.capital_inicial} USDT → final: {res.capital_final:.2f} USDT (**{ret:+.2f} %**)",
         f"- Velas evaluadas: {res.velas_evaluadas} | señales de la estrategia: {res.senales} | "
         f"aprobadas por el motor de riesgo: {res.aprobadas}", ""]
    if res.rechazos:
        l.append("Motivos de rechazo del motor (una señal puede tener varios):")
        l += [f"- {m}: {c}" for m, c in res.rechazos.most_common()]
        l.append("")
    l += _bloque("Total", total)
    l += _bloque(f"Primer tramo (hasta {_fecha(corte)})", calcular(a, res.capital_inicial))
    l += _bloque(f"Tramo final (desde {_fecha(corte)}) – revisa si se parece al primero", calcular(b, res.capital_inicial))
    if total.operaciones and total.bruto > 0 and total.comisiones > 0:
        l.append(f"Las comisiones se llevaron el {total.comisiones / total.bruto * CIEN:.0f} % del resultado bruto.")
        l.append("")
    if total.operaciones < 30:
        l.append(f"⚠️ Solo {total.operaciones} operaciones: es muy poca muestra para sacar conclusiones.")
        l.append("")
    l.append("Supuestos: " + "; ".join(notas))
    return "\n".join(l) + "\n"
