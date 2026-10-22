from decimal import Decimal

import pytest
from pydantic import ValidationError

from futuros.config import Config, load


def base(**over):
    d = dict(capital_referencia_usdt=500, objetivo_neto_por_operacion_usdt=1.5, apalancamiento_max=2,
             mercados=["BTCUSDT"], direcciones=["LONG", "SHORT"], modo="simulacion",
             riesgo_por_operacion_pct=0.5, perdida_diaria_max_pct=3, exposicion_max_pct=200, posiciones_abiertas_max=1)
    d.update(over)
    return d


def test_default_config_loads():
    c = load()
    assert c.capital_referencia_usdt == Decimal("500") and c.apalancamiento_max == Decimal("2") and c.modo == "simulacion"


@pytest.mark.parametrize("lev", [2.01, 3, 10, 125])
def test_leverage_above_2x_is_rejected(lev):
    with pytest.raises(ValidationError):
        Config(**base(apalancamiento_max=lev))


def test_exposure_cannot_exceed_leverage():
    with pytest.raises(ValidationError):
        Config(**base(apalancamiento_max=1, exposicion_max_pct=150))


@pytest.mark.parametrize("bad", [dict(modo="yolo"), dict(direcciones=["UP"]), dict(riesgo_por_operacion_pct=5),
                                 dict(perdida_diaria_max_pct=50), dict(capital_referencia_usdt=0)])
def test_invalid_values_rejected(bad):
    with pytest.raises(ValidationError):
        Config(**base(**bad))
