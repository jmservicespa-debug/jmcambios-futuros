from decimal import Decimal

import pytest

from futuros.data.rest import ClienteREST, IPBloqueada, LimiteBinance, PresupuestoPesoAgotado
from simulado import AHORA_MS, BASE_VELA, transporte


def cliente(registro=None, **kw):
    opciones = {k: kw.pop(k) for k in ("tope_peso",) if k in kw}
    return ClienteREST(transport=transporte(registro, **kw), reloj=lambda: AHORA_MS / 1000, **opciones)


def test_solo_usa_endpoints_publicos_get_y_sin_llaves():
    reg = []
    with cliente(reg) as c:
        c.hora_servidor_ms(); c.velas("BTCUSDT"); c.libro("ETHUSDT"); c.mark_price("BTCUSDT"); c.historial_funding("BTCUSDT")
    assert {r.url.path for r in reg} == {"/fapi/v1/time", "/fapi/v1/klines", "/fapi/v1/depth",
                                         "/fapi/v1/premiumIndex", "/fapi/v1/fundingRate"}
    assert all(r.method == "GET" and r.url.host == "fapi.binance.com" for r in reg)
    for r in reg:
        assert "X-MBX-APIKEY" not in r.headers and "signature" not in r.url.params


def test_velas_se_convierten_a_decimal():
    with cliente() as c:
        vs = c.velas("btcusdt", "1m", 5)
    assert len(vs) == 5 and vs[0].simbolo == "BTCUSDT"
    assert vs[-1].apertura_ms == BASE_VELA and vs[-1].cierre == Decimal("100.5")
    assert vs[0].cerrada and not vs[-1].cerrada      # la última vela sigue abierta


def test_libro_mark_y_funding():
    with cliente() as c:
        lb = c.libro("BTCUSDT", 20)
        mp = c.mark_price("BTCUSDT")
        fh = c.historial_funding("BTCUSDT", 3)
    assert lb.mejor_bid == Decimal("100.40") and lb.mejor_ask == Decimal("100.60") and lb.ts_ms == AHORA_MS
    assert mp.mark == Decimal("100.50") and mp.funding == Decimal("0.0001")
    assert fh[0].tasa == Decimal("0.0001")


def test_lee_peso_usado_de_la_cabecera():
    with cliente() as c:
        c.mark_price("BTCUSDT")
        assert c.peso_usado == 7


def test_respeta_tope_propio_de_peso():
    reg = []
    with cliente(reg, tope_peso=8) as c:
        c.mark_price("BTCUSDT")              # Binance informa 7 usados
        with pytest.raises(PresupuestoPesoAgotado):
            c.libro("BTCUSDT", 20)           # peso 2: 7 + 2 > 8, no se envía
    assert len(reg) == 1


def test_429_detiene_y_entrega_retry_after():
    reg = []
    with cliente(reg, estado=429, cabeceras={"Retry-After": "30"}) as c:
        with pytest.raises(LimiteBinance) as e:
            c.velas("BTCUSDT")
    assert e.value.reintentar_en == 30 and len(reg) == 1   # no reintenta por su cuenta


def test_418_ip_bloqueada():
    with cliente(estado=418, cabeceras={"Retry-After": "120"}) as c:
        with pytest.raises(IPBloqueada):
            c.mark_price("BTCUSDT")


@pytest.mark.parametrize("llamada", [
    lambda c: c.velas("BTC USDT"), lambda c: c.velas("BTCUSDT", "7m"), lambda c: c.velas("BTCUSDT", limit=2000),
    lambda c: c.libro("BTCUSDT", 25), lambda c: c.historial_funding("BTCUSDT", 0)])
def test_parametros_invalidos_no_llegan_a_binance(llamada):
    reg = []
    with cliente(reg) as c:
        with pytest.raises(ValueError):
            llamada(c)
    assert reg == []
