from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futuros.data.modelos import Libro, Vela
from futuros.strategy import LONG, NINGUNA, SHORT, EstrategiaConfig, evaluar

D = Decimal
PASO = 300_000


def serie(cierres, volumenes=None, simbolo="BTCUSDT"):
    """Velas de 5m cerradas: apertura = cierre anterior, máximo/mínimo a ±0,2 % del cuerpo."""
    volumenes = volumenes or ["1"] * len(cierres)
    out, prev = [], D(cierres[0])
    for i, (c, v) in enumerate(zip(cierres, volumenes)):
        c = D(c)
        out.append(Vela(simbolo, "5m", i * PASO, (i + 1) * PASO - 1, prev, max(prev, c) * D("1.002"),
                        min(prev, c) * D("0.998"), c, D(v)))
        prev = c
    return out


def tendencia_y_giro(sube: bool, volumen_final="3"):
    """60 velas con tendencia suave en un sentido y una última vela fuerte en el otro (provoca el cruce)."""
    paso = D("-0.01") if sube else D("0.01")
    cierres = [D(100) + paso * i for i in range(60)]
    cierres.append(cierres[-1] + (D(1) if sube else D(-1)))
    return serie(cierres, ["1"] * 60 + [volumen_final])


LIBRO_ANGOSTO = Libro("BTCUSDT", 0, 1, [(D("100.39"), D(1))], [(D("100.40"), D(1))])


def test_senal_long():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True), libro=LIBRO_ANGOSTO)
    assert s.direccion == LONG, s.motivos
    assert s.stop < s.precio_ref < s.objetivo
    a = s.indicadores["atr"]
    assert abs((s.precio_ref - s.stop) - D("1.5") * a) < D("1e-20")
    assert abs((s.objetivo - s.precio_ref) - D("2") * a) < D("1e-20")


def test_senal_short():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=False))
    assert s.direccion == SHORT, s.motivos
    assert s.objetivo < s.precio_ref < s.stop


def test_misma_entrada_misma_salida():
    vs = tendencia_y_giro(sube=True)
    assert evaluar("BTCUSDT", vs) == evaluar("BTCUSDT", list(vs))


def test_datos_no_aptos_no_dan_senal():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True), datos_aptos=False, motivos_calidad=("libro: cruzado",))
    assert s.direccion == NINGUNA and "datos NO APTOS: libro: cruzado" in s.motivos


def test_pocas_velas():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True)[-20:])
    assert s.direccion == NINGUNA and "faltan velas" in s.motivos[0]


def test_sin_cruce():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True)[:-1])
    assert s.direccion == NINGUNA and s.motivos == ["sin cruce de EMAs en la última vela cerrada"]


def test_vela_abierta_se_ignora():
    vs = tendencia_y_giro(sube=True)
    loca = replace(vs[-1], apertura_ms=vs[-1].apertura_ms + PASO, cierre_ms=vs[-1].cierre_ms + PASO,
                   cierre=D("50"), minimo=D("49"), cerrada=False)
    assert evaluar("BTCUSDT", vs + [loca]) == evaluar("BTCUSDT", vs)


def test_direccion_no_permitida():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=False), direcciones=("LONG",))
    assert s.direccion == NINGUNA and any("SHORT no permitida" in m for m in s.motivos)


def test_volumen_bajo_descarta():
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True, volumen_final="1"))
    assert s.direccion == NINGUNA and any("volumen" in m and "descartada" in m for m in s.motivos)


def test_objetivo_que_no_cubre_comisiones_descarta():
    cfg = EstrategiaConfig(comision_pct=D("0.5"))
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True), cfg)
    assert s.direccion == NINGUNA and any("comisiones" in m for m in s.motivos)


def test_mercado_quieto_descarta():
    cfg = EstrategiaConfig(atr_min_pct=D("1"), atr_max_pct=D("2"))
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True), cfg)
    assert s.direccion == NINGUNA and any("muy quieto" in m for m in s.motivos)


def test_spread_ancho_descarta():
    ancho = Libro("BTCUSDT", 0, 1, [(D("100"), D(1))], [(D("100.5"), D(1))])
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True), libro=ancho)
    assert s.direccion == NINGUNA and any("spread" in m for m in s.motivos)


@pytest.mark.parametrize("malo", [dict(ema_rapida=21, ema_lenta=9), dict(intervalo="7m"),
                                  dict(atr_min_pct=2, atr_max_pct=1), dict(stop_atr=0)])
def test_config_invalida(malo):
    with pytest.raises(ValidationError):
        EstrategiaConfig(**malo)


def test_filtro_de_costos_usa_taker_mas_maker_por_tres():
    cfg = EstrategiaConfig(comision_pct=D("0.3"), comision_maker_pct=D("0.2"))   # 3 × 0,5 % = 1,5 % > objetivo (~0,96 %)
    s = evaluar("BTCUSDT", tendencia_y_giro(sube=True), cfg)
    assert s.direccion == NINGUNA and any("3× las comisiones de entrada y salida (0.5 %)" in m for m in s.motivos)
