"""Estructuras de datos de mercado. Precios y cantidades en Decimal (nunca float)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Vela:
    simbolo: str
    intervalo: str
    apertura_ms: int
    cierre_ms: int
    apertura: Decimal
    maximo: Decimal
    minimo: Decimal
    cierre: Decimal
    volumen: Decimal
    cerrada: bool = True


@dataclass(frozen=True)
class Libro:
    simbolo: str
    ts_ms: int                       # hora del evento según Binance
    ultimo_update_id: int
    bids: list[tuple[Decimal, Decimal]] = field(default_factory=list)   # (precio, cantidad), mejor primero
    asks: list[tuple[Decimal, Decimal]] = field(default_factory=list)

    @property
    def mejor_bid(self) -> Decimal | None:
        return self.bids[0][0] if self.bids else None

    @property
    def mejor_ask(self) -> Decimal | None:
        return self.asks[0][0] if self.asks else None

    @property
    def medio(self) -> Decimal | None:
        if self.mejor_bid is None or self.mejor_ask is None:
            return None
        return (self.mejor_bid + self.mejor_ask) / 2


@dataclass(frozen=True)
class MarkPrice:
    simbolo: str
    ts_ms: int
    mark: Decimal
    indice: Decimal
    funding: Decimal                 # última tasa de funding (ej. 0.0001 = 0,01 %)
    proximo_funding_ms: int


@dataclass(frozen=True)
class Funding:
    simbolo: str
    ts_ms: int
    tasa: Decimal


@dataclass(frozen=True)
class ReglasSimbolo:
    """Reglas del exchange para un símbolo (de /fapi/v1/exchangeInfo)."""
    simbolo: str
    tick_precio: Decimal         # PRICE_FILTER.tickSize
    paso_cantidad: Decimal       # LOT_SIZE / MARKET_LOT_SIZE, el más estricto
    cantidad_min: Decimal
    cantidad_max: Decimal
    nocional_min: Decimal        # MIN_NOTIONAL.notional
