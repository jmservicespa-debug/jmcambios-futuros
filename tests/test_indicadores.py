from decimal import Decimal

import pytest

from futuros.data.modelos import Vela
from futuros.features import atr, ema, rango_verdadero, volumen_promedio, vwap

D = Decimal


def vela(i, o, h, l, c, v="1"):
    return Vela("BTCUSDT", "5m", i * 300_000, (i + 1) * 300_000 - 1, D(o), D(h), D(l), D(c), D(v))


def test_ema_valores_a_mano():
    # n=3: arranca con promedio(1,2,3)=2; k=0,5 -> 3 -> 4
    assert ema([D(x) for x in (1, 2, 3, 4, 5)], 3) == [None, None, D(2), D(3), D(4)]


def test_ema_de_serie_constante_es_constante():
    assert ema([D("100")] * 30, 9)[-1] == D("100")


def test_ema_sin_datos_suficientes():
    assert ema([D(1), D(2)], 3) == [None, None]
    with pytest.raises(ValueError):
        ema([D(1)], 0)


def test_rango_verdadero_considera_cierre_anterior():
    vs = [vela(0, 10, 11, 9, 10), vela(1, 13, 14, 12, 13)]   # hueco al alza: TR = 14 - 10 = 4
    assert rango_verdadero(vs) == [None, D(4)]


def test_atr_wilder_a_mano():
    vs = [vela(0, 10, 11, 9, 10), vela(1, 10, 12, 10, 11), vela(2, 11, 12, 10, 11), vela(3, 11, 15, 11, 14)]
    # TR = [-, 2, 2, 4]; n=2: primer ATR = (2+2)/2 = 2; luego (2*1 + 4)/2 = 3
    assert atr(vs, 2) == [None, None, D(2), D(3)]


def test_vwap_pondera_por_volumen():
    vs = [vela(0, 9, 12, 9, 9, "1"), vela(1, 9, 21, 15, 18, "3")]   # precios típicos 10 y 18
    assert vwap(vs, 2) == [None, D(16)]                              # (10*1 + 18*3) / 4


def test_volumen_promedio_excluye_vela_actual():
    vs = [vela(i, 1, 1, 1, 1, v) for i, v in enumerate(("1", "3", "100"))]
    assert volumen_promedio(vs, 2) == [None, None, D(2)]
