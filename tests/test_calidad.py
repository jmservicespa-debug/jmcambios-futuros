from dataclasses import replace
from decimal import Decimal

from futuros.data.modelos import Libro, MarkPrice, Vela
from futuros.quality import MonitorConexion, evaluar
from futuros.quality.verificador import revisar_libro, revisar_mark, revisar_reloj, revisar_velas
from simulado import AHORA_MS, BASE_VELA, MIN

D = Decimal


def velas(n=5, cierres=None):
    cierres = cierres or ["100"] * n
    return [Vela("BTCUSDT", "1m", BASE_VELA - (n - 1 - i) * MIN, BASE_VELA - (n - 2 - i) * MIN - 1,
                 D(c), D(c) * D("1.001"), D(c) * D("0.999"), D(c), D("1")) for i, c in enumerate(cierres)]


LIBRO = Libro("BTCUSDT", AHORA_MS, 1, [(D("99.99"), D("1"))], [(D("100.01"), D("1"))])
MARK = MarkPrice("BTCUSDT", AHORA_MS, D("100"), D("100.02"), D("0.0001"), AHORA_MS + 1)


def test_datos_sanos_son_aptos():
    r = evaluar("BTCUSDT", velas(), LIBRO, MARK, AHORA_MS)
    assert r.apto, r.motivos


def test_hueco_en_velas():
    vs = velas(6)
    del vs[2:4]
    m = revisar_velas(vs, AHORA_MS)
    assert any("faltan 2 vela" in x for x in m)


def test_velas_duplicadas_o_desordenadas():
    vs = velas(3)
    assert any("desordenadas" in x for x in revisar_velas([vs[0], vs[2], vs[1]], AHORA_MS))


def test_salto_anormal():
    m = revisar_velas(velas(3, ["100", "100", "110"]), AHORA_MS)
    assert any("salto anormal" in x for x in m)


def test_ohlc_incoherente():
    vs = velas(2)
    vs[1] = replace(vs[1], cierre=D("200"))
    assert any("incoherentes" in x for x in revisar_velas(vs, AHORA_MS))


def test_velas_viejas():
    assert any("viejos" in x for x in revisar_velas(velas(), AHORA_MS + 5 * MIN))


def test_libro_viejo_cruzado_o_vacio():
    assert any("viejos" in x for x in revisar_libro(LIBRO, AHORA_MS + 6_000))
    cruzado = replace(LIBRO, bids=[(D("100.02"), D("1"))])
    assert any("cruzado" in x for x in revisar_libro(cruzado, AHORA_MS))
    assert revisar_libro(replace(LIBRO, asks=[]), AHORA_MS) == ["libro: vacío o sin datos"]


def test_libro_lejos_del_mark():
    lejos = replace(LIBRO, bids=[(D("101"), D("1"))], asks=[(D("101.02"), D("1"))])
    assert any("se aleja" in x for x in revisar_libro(lejos, AHORA_MS, MARK))


def test_mark_viejo_o_lejos_del_indice():
    assert any("viejos" in x for x in revisar_mark(MARK, AHORA_MS + 10_000))
    assert any("índice" in x for x in revisar_mark(replace(MARK, indice=D("90")), AHORA_MS))
    assert revisar_mark(None, AHORA_MS) == ["mark price: sin datos"]


def test_reloj_desfasado():
    assert revisar_reloj(500) == []
    assert revisar_reloj(-5_000)


def test_desconexion_marca_no_apto():
    mon = MonitorConexion()
    mon.cambio_estado("market", True, "conectado")
    for t in ("vela", "libro", "mark"):
        mon.mensaje("BTCUSDT", t, AHORA_MS)
    assert evaluar("BTCUSDT", velas(), LIBRO, MARK, AHORA_MS, monitor=mon).apto
    mon.cambio_estado("market", False, "ConnectionResetError")
    r = evaluar("BTCUSDT", velas(), LIBRO, MARK, AHORA_MS, monitor=mon)
    assert not r.apto and any("caída" in x for x in r.motivos) and mon.desconexiones["market"] == 1


def test_stream_en_silencio_marca_no_apto():
    mon = MonitorConexion()
    mon.cambio_estado("public", True, "conectado")
    mon.mensaje("BTCUSDT", "libro", AHORA_MS - 15_000)
    m = mon.revisar("BTCUSDT", ["libro", "mark"], AHORA_MS)
    assert any("sin mensajes hace 15 s" in x for x in m) and any("aún no llega" in x for x in m)
