from decimal import Decimal

from futuros.backtest import informe
from futuros.backtest.simulador import ParametrosBacktest, correr
from futuros.config import Config
from futuros.data.modelos import ReglasSimbolo, Vela
from futuros.strategy import LONG, NINGUNA, EstrategiaConfig, Senal
from test_estrategia import tendencia_y_giro
from test_riesgo import BASE

D = Decimal
P = 300_000
CFG = Config(**BASE)
EST = EstrategiaConfig(ema_rapida=2, ema_lenta=3, atr_periodo=2, vwap_periodo=2, vol_periodo=2)   # 4 velas mínimas
PAR = ParametrosBacktest(ventana=4)
REGLAS = {"ETHUSDT": ReglasSimbolo("ETHUSDT", D("0.01"), D("0.001"), D("0.001"), D("10000"), D("20")),
          "BTCUSDT": ReglasSimbolo("BTCUSDT", D("0.01"), D("0.001"), D("0.001"), D("10000"), D("20"))}


def v(i, o="2000", h="2001", l="1999", c="2000", s="ETHUSDT"):
    return Vela(s, "5m", i * P, (i + 1) * P - 1, D(o), D(h), D(l), D(c), D(1))


def planas(n, s="ETHUSDT"):
    return [v(i, s=s) for i in range(n)]


def long_en(*indices):
    """Generador falso: LONG con stop 1980 y objetivo 2040 al cierre de las velas indicadas."""
    def gen(s, ventana, apto, motivos):
        if ventana[-1].apertura_ms // P in indices:
            return Senal(s, LONG, ventana[-1].apertura_ms, ventana[-1].cierre, D("1980"), D("2040"))
        return Senal(s, NINGUNA, ventana[-1].apertura_ms)
    return gen


def correr_eth(velas, gen, **kw):
    return correr({"ETHUSDT": velas}, CFG, EST, REGLAS, PAR, gen, **kw)


def test_gana_en_el_objetivo_con_comisiones_y_deslizamiento_exactos():
    vs = planas(6) + [v(6, h="2045"), v(7)]
    r = correr_eth(vs, long_en(5))
    assert r.senales == 1 and r.aprobadas == 1 and len(r.operaciones) == 1
    o = r.operaciones[0]
    entrada = D("2000") * D("1.0002")                       # apertura siguiente + 0,02 % en contra
    assert o.motivo_salida == "objetivo" and o.precio_entrada == entrada and o.cantidad == D("0.113")
    assert o.bruto == (D("2040") - entrada) * D("0.113")
    assert o.comisiones == D("0.113") * (entrada + D("2040")) * D("0.0005")
    assert o.neto == o.bruto - o.comisiones and r.capital_final == D(500) + o.neto


def test_pierde_en_el_stop():
    r = correr_eth(planas(6) + [v(6, l="1975"), v(7)], long_en(5))
    o = r.operaciones[0]
    assert o.motivo_salida == "stop" and o.precio_salida == D("1980") * D("0.9998") and o.neto < 0
    assert -o.neto <= D("2.6")                              # ~0,5 % de 500 (más deslizamiento)


def test_stop_y_objetivo_en_la_misma_vela_cuenta_como_stop():
    r = correr_eth(planas(6) + [v(6, h="2045", l="1975"), v(7)], long_en(5))
    assert r.operaciones[0].motivo_salida == "stop"


def test_salto_sobre_el_stop_sale_en_la_apertura():
    r = correr_eth(planas(7) + [v(7, o="1970", h="1972", l="1960", c="1965"), v(8)], long_en(5))
    o = r.operaciones[0]
    assert o.motivo_salida == "salto sobre el stop" and o.precio_salida == D("1970") * D("0.9998")


def test_si_la_vela_de_entrada_abre_bajo_el_stop_sale_de_inmediato():
    r = correr_eth(planas(6) + [v(6, o="1970", h="1972", l="1960", c="1965"), v(7)], long_en(5))
    o = r.operaciones[0]
    assert o.entrada_ms == o.salida_ms and o.motivo_salida == "salto sobre el stop"


def test_posicion_abierta_al_final_se_cierra_al_ultimo_cierre():
    r = correr_eth(planas(9), long_en(5))
    assert r.operaciones[0].motivo_salida == "fin de datos" and r.operaciones[0].precio_salida == D("2000")


def test_freno_de_perdida_diaria_en_el_backtest():
    vs = [v(i, l="1975") for i in range(40)]                # cada operación toca el stop
    r = correr_eth(vs, long_en(*range(40)))
    assert r.rechazos["pérdida diaria"] > 0
    assert sum(o.neto for o in r.operaciones) >= D("-15.5")   # 3 % de 500, más deslizamiento


def test_nunca_hay_dos_posiciones_a_la_vez():
    series = {"ETHUSDT": planas(20), "BTCUSDT": planas(20, s="BTCUSDT")}
    r = correr(series, CFG, EST, REGLAS, PAR, long_en(*range(20)))
    ops = sorted(r.operaciones, key=lambda o: o.entrada_ms)
    assert len(ops) >= 1
    for a, b in zip(ops, ops[1:]):
        assert b.entrada_ms > a.salida_ms


def test_huecos_marcan_datos_no_aptos():
    vistos = []

    def gen(s, ventana, apto, motivos):
        vistos.append((ventana[-1].apertura_ms // P, apto))
        return Senal(s, NINGUNA, 0)

    vs = planas(5) + [v(i) for i in range(7, 14)]           # faltan las velas 5 y 6
    correr_eth(vs, gen)
    aptos = dict(vistos)
    assert aptos[4] and not aptos[7] and not aptos[9] and aptos[10]


def test_resultado_reproducible():
    vs = planas(6) + [v(6, h="2045"), v(7, l="1975")] + planas(20)[8:]
    assert correr_eth(vs, long_en(5, 10)) == correr_eth(vs, long_en(5, 10))


def test_con_la_estrategia_real_de_punta_a_punta():
    vs = tendencia_y_giro(sube=True)                        # cruce alcista en la última vela (índice 60)
    ultimo = vs[-1].cierre
    for k in range(1, 6):                                   # después el precio sigue subiendo
        c = ultimo + D(k)
        vs.append(Vela("BTCUSDT", "5m", (60 + k) * P, (61 + k) * P - 1, c - 1, c + D("0.2"), c - D("1.2"), c, D(1)))
    reglas = {"BTCUSDT": ReglasSimbolo("BTCUSDT", D("0.01"), D("0.001"), D("0.001"), D("10000"), D("5"))}
    r = correr({"BTCUSDT": vs}, CFG, EstrategiaConfig(), reglas, ParametrosBacktest(ventana=60))
    assert r.senales == 1 and r.aprobadas == 1
    assert r.operaciones[0].direccion == LONG and r.operaciones[0].motivo_salida == "objetivo"


def test_metricas_a_mano():
    from types import SimpleNamespace as N
    ops = [N(neto=D(x), bruto=D(x), comisiones=D(0)) for x in (2, -1, -1, 3, -2)]
    m = informe.calcular(ops, D(100))
    assert (m.operaciones, m.ganadoras, m.neto, m.peor_racha) == (5, 2, D(1), 2)
    assert m.tasa_acierto_pct == D(40) and m.factor_beneficio == D("1.25")
    assert m.caida_max_usdt == D(2) and abs(m.caida_max_pct - D(200) / D(102)) < D("1e-20")


def test_informe_avisa_muestra_chica_y_comisiones():
    r = correr_eth(planas(6) + [v(6, h="2045"), v(7)], long_en(5))
    t = informe.texto(r, ["ETHUSDT"], "5m", ["supuesto de prueba"])
    assert "No garantiza resultados futuros" in t and "muy poca muestra" in t
    assert "Las comisiones se llevaron" in t and "Primer tramo" in t and "Tramo final" in t
