"""Indicadores técnicos con Decimal (resultado idéntico en cualquier PC).

Cada función devuelve una lista alineada con las velas de entrada; las posiciones
sin datos suficientes valen None. Solo se deben usar velas CERRADAS.
"""
from __future__ import annotations

from decimal import Decimal

from futuros.data.modelos import Vela

TRES = Decimal(3)


def ema(valores: list[Decimal], n: int) -> list[Decimal | None]:
    """Media móvil exponencial. Arranca con el promedio simple de los primeros n valores."""
    if n < 1:
        raise ValueError("n debe ser >= 1")
    out: list[Decimal | None] = [None] * len(valores)
    if len(valores) < n:
        return out
    k = Decimal(2) / Decimal(n + 1)
    actual = sum(valores[:n], Decimal(0)) / n
    out[n - 1] = actual
    for i in range(n, len(valores)):
        actual = valores[i] * k + actual * (1 - k)
        out[i] = actual
    return out


def rango_verdadero(velas: list[Vela]) -> list[Decimal | None]:
    out: list[Decimal | None] = [None]
    for prev, v in zip(velas, velas[1:]):
        out.append(max(v.maximo - v.minimo, abs(v.maximo - prev.cierre), abs(v.minimo - prev.cierre)))
    return out if velas else []


def atr(velas: list[Vela], n: int = 14) -> list[Decimal | None]:
    """Average True Range con el suavizado de Wilder."""
    if n < 1:
        raise ValueError("n debe ser >= 1")
    tr = rango_verdadero(velas)
    out: list[Decimal | None] = [None] * len(velas)
    if len(velas) < n + 1:
        return out
    actual = sum(tr[1:n + 1], Decimal(0)) / n
    out[n] = actual
    for i in range(n + 1, len(velas)):
        actual = (actual * (n - 1) + tr[i]) / n
        out[i] = actual
    return out


def vwap(velas: list[Vela], n: int) -> list[Decimal | None]:
    """VWAP móvil de las últimas n velas, con precio típico (máximo + mínimo + cierre) / 3."""
    out: list[Decimal | None] = [None] * len(velas)
    for i in range(n - 1, len(velas)):
        ventana = velas[i - n + 1:i + 1]
        vol = sum((v.volumen for v in ventana), Decimal(0))
        if vol > 0:
            out[i] = sum(((v.maximo + v.minimo + v.cierre) / TRES * v.volumen for v in ventana), Decimal(0)) / vol
    return out


def volumen_promedio(velas: list[Vela], n: int) -> list[Decimal | None]:
    """Promedio de volumen de las n velas ANTERIORES (no incluye la vela actual)."""
    out: list[Decimal | None] = [None] * len(velas)
    for i in range(n, len(velas)):
        out[i] = sum((v.volumen for v in velas[i - n:i]), Decimal(0)) / n
    return out
