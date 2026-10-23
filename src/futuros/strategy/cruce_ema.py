"""Estrategia cuantitativa de scalping: cruce de EMAs con filtros de VWAP, volumen, ATR, spread y costos.

Solo PROPONE una señal (LONG, SHORT o NINGUNA) con precio de referencia, stop y objetivo.
No calcula tamaño ni apalancamiento y no envía nada: eso es del motor de riesgo (Fase 4).
Misma entrada => misma salida (todo en Decimal, sin azar ni hora local).
No hay ninguna garantía de rentabilidad; las reglas se validarán con backtest (Fase 5).

Reglas (sobre la última vela CERRADA):
- LONG : la EMA rápida cruza hacia arriba a la EMA lenta, el cierre queda sobre el VWAP
         y el volumen supera `vol_factor` veces el promedio.
- SHORT: lo mismo hacia abajo y con el cierre bajo el VWAP.
- Filtros: datos APTOS, dirección permitida, ATR dentro de la banda, spread bajo
           y objetivo suficiente para cubrir las comisiones de entrada y salida.
- Stop = precio ∓ stop_atr × ATR · Objetivo = precio ± objetivo_atr × ATR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from futuros.data.endpoints import INTERVALOS_MS
from futuros.data.modelos import Libro, Vela
from futuros.features import atr, ema, volumen_promedio, vwap

LONG, SHORT, NINGUNA = "LONG", "SHORT", "NINGUNA"
CIEN = Decimal(100)


class EstrategiaConfig(BaseModel):
    intervalo: str = "5m"
    ema_rapida: int = Field(9, ge=2)
    ema_lenta: int = Field(21, ge=3)
    atr_periodo: int = Field(14, ge=2)
    vwap_periodo: int = Field(48, ge=2)
    vol_periodo: int = Field(20, ge=2)
    vol_factor: Decimal = Field(Decimal("1.2"), ge=0)
    stop_atr: Decimal = Field(Decimal("1.5"), gt=0)
    objetivo_atr: Decimal = Field(Decimal("2"), gt=0)
    atr_min_pct: Decimal = Field(Decimal("0.08"), ge=0)
    atr_max_pct: Decimal = Field(Decimal("1.5"), gt=0)
    spread_max_pct: Decimal = Field(Decimal("0.05"), gt=0)
    comision_pct: Decimal = Field(Decimal("0.05"), ge=0)   # por lado (taker); verificar en tu cuenta
    costo_min_factor: Decimal = Field(Decimal("2"), ge=1)  # objetivo >= factor × costo ida y vuelta

    @model_validator(mode="after")
    def _coherencia(self) -> "EstrategiaConfig":
        if self.intervalo not in INTERVALOS_MS:
            raise ValueError(f"intervalo no soportado: {self.intervalo}")
        if self.ema_rapida >= self.ema_lenta:
            raise ValueError("la EMA rápida debe ser menor que la lenta")
        if self.atr_min_pct >= self.atr_max_pct:
            raise ValueError("atr_min_pct debe ser menor que atr_max_pct")
        return self

    @property
    def velas_minimas(self) -> int:
        return max(self.ema_lenta + 1, self.atr_periodo + 1, self.vwap_periodo, self.vol_periodo + 1)


@dataclass(frozen=True)
class Senal:
    simbolo: str
    direccion: str                     # LONG | SHORT | NINGUNA
    vela_ms: int                       # apertura de la vela cerrada evaluada (0 si no hubo)
    precio_ref: Decimal | None = None
    stop: Decimal | None = None
    objetivo: Decimal | None = None
    motivos: list[str] = field(default_factory=list)
    indicadores: dict[str, Decimal] = field(default_factory=dict)


def _pct(a: Decimal, b: Decimal) -> Decimal:
    return a / b * CIEN


def evaluar(simbolo: str, velas: list[Vela], cfg: EstrategiaConfig = EstrategiaConfig(),
            direcciones: tuple[str, ...] = (LONG, SHORT), libro: Libro | None = None,
            datos_aptos: bool = True, motivos_calidad: tuple[str, ...] = ()) -> Senal:
    cerradas = [v for v in velas if v.cerrada and v.simbolo == simbolo and v.intervalo == cfg.intervalo]
    if not datos_aptos:
        return Senal(simbolo, NINGUNA, cerradas[-1].apertura_ms if cerradas else 0,
                     motivos=["datos NO APTOS: " + "; ".join(motivos_calidad or ("sin detalle",))])
    if len(cerradas) < cfg.velas_minimas:
        return Senal(simbolo, NINGUNA, cerradas[-1].apertura_ms if cerradas else 0,
                     motivos=[f"faltan velas cerradas: hay {len(cerradas)}, se necesitan {cfg.velas_minimas}"])

    cierres = [v.cierre for v in cerradas]
    rapida, lenta = ema(cierres, cfg.ema_rapida), ema(cierres, cfg.ema_lenta)
    # Solo se usa el último valor: se pasan solo las velas necesarias (mismo resultado, mucho más rápido).
    a = atr(cerradas, cfg.atr_periodo)[-1]
    vw = vwap(cerradas[-cfg.vwap_periodo:], cfg.vwap_periodo)[-1]
    vp = volumen_promedio(cerradas[-(cfg.vol_periodo + 1):], cfg.vol_periodo)[-1]
    ultima = cerradas[-1]
    precio = ultima.cierre
    ind = {"ema_rapida": rapida[-1], "ema_lenta": lenta[-1], "atr": a, "vwap": vw, "volumen": ultima.volumen,
           "volumen_promedio": vp}
    base = dict(simbolo=simbolo, vela_ms=ultima.apertura_ms, precio_ref=precio, indicadores=ind)

    # 1) ¿Hay patrón de entrada?
    if rapida[-2] <= lenta[-2] and rapida[-1] > lenta[-1]:
        direccion = LONG
    elif rapida[-2] >= lenta[-2] and rapida[-1] < lenta[-1]:
        direccion = SHORT
    else:
        return Senal(direccion=NINGUNA, motivos=["sin cruce de EMAs en la última vela cerrada"], **base)

    motivos = [f"cruce {'alcista' if direccion == LONG else 'bajista'} de EMA {cfg.ema_rapida}/{cfg.ema_lenta}"]
    rechazos: list[str] = []

    # 2) Confirmaciones
    if vw is None:
        rechazos.append("VWAP sin volumen")
    elif direccion == LONG and precio <= vw:
        rechazos.append(f"cierre {precio} no está sobre el VWAP {vw:.2f}")
    elif direccion == SHORT and precio >= vw:
        rechazos.append(f"cierre {precio} no está bajo el VWAP {vw:.2f}")
    else:
        motivos.append(f"cierre {'sobre' if direccion == LONG else 'bajo'} el VWAP {vw:.2f}")
    if ultima.volumen < vp * cfg.vol_factor:
        rechazos.append(f"volumen {ultima.volumen} menor a {cfg.vol_factor}× el promedio ({vp:.2f})")
    else:
        motivos.append(f"volumen {ultima.volumen} ≥ {cfg.vol_factor}× el promedio")

    # 3) Filtros de riesgo de mercado y costos
    if direccion not in direcciones:
        rechazos.append(f"dirección {direccion} no permitida en la configuración")
    atr_pct = _pct(a, precio)
    if atr_pct < cfg.atr_min_pct:
        rechazos.append(f"mercado muy quieto: ATR {atr_pct:.3f} % < {cfg.atr_min_pct} %")
    elif atr_pct > cfg.atr_max_pct:
        rechazos.append(f"mercado muy agitado: ATR {atr_pct:.3f} % > {cfg.atr_max_pct} %")
    objetivo_pct = atr_pct * cfg.objetivo_atr
    costo_pct = cfg.comision_pct * 2
    if objetivo_pct < costo_pct * cfg.costo_min_factor:
        rechazos.append(f"objetivo {objetivo_pct:.3f} % no cubre {cfg.costo_min_factor}× las comisiones "
                        f"de ida y vuelta ({costo_pct} %)")
    if libro is not None:
        if libro.mejor_bid is None or libro.mejor_ask is None:
            rechazos.append("libro sin precios")
        else:
            spread_pct = _pct(libro.mejor_ask - libro.mejor_bid, libro.medio)
            if spread_pct > cfg.spread_max_pct:
                rechazos.append(f"spread {spread_pct:.3f} % > {cfg.spread_max_pct} %")

    if rechazos:
        return Senal(direccion=NINGUNA, motivos=motivos + ["descartada: " + r for r in rechazos], **base)

    signo = 1 if direccion == LONG else -1
    return Senal(direccion=direccion, stop=precio - signo * cfg.stop_atr * a,
                 objetivo=precio + signo * cfg.objetivo_atr * a, motivos=motivos, **base)
