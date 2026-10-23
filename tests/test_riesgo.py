from dataclasses import replace
from decimal import Decimal

import pytest

from futuros.config import Config
from futuros.data.modelos import ReglasSimbolo
from futuros.risk import EstadoCuenta, MotorRiesgo, PosicionAbierta
from futuros.strategy import LONG, NINGUNA, SHORT, Senal

D = Decimal
BASE = dict(capital_referencia_usdt=500, objetivo_neto_por_operacion_usdt=1.5, apalancamiento_max=2,
            mercados=["BTCUSDT", "ETHUSDT"], direcciones=["LONG", "SHORT"], modo="simulacion",
            riesgo_por_operacion_pct=0.5, perdida_diaria_max_pct=3, exposicion_max_pct=200, posiciones_abiertas_max=1)
REGLAS = ReglasSimbolo("ETHUSDT", D("0.01"), D("0.001"), D("0.001"), D("10000"), D("20"))
CUENTA = EstadoCuenta(D(500))
LARGO = Senal("ETHUSDT", LONG, 0, D("2000"), D("1980"), D("2040"))
CORTO = Senal("ETHUSDT", SHORT, 0, D("2000"), D("2020"), D("1960"))


def motor(**over):
    return MotorRiesgo(Config(**{**BASE, **over}), D("0.05"))


def test_aprueba_long_con_tamano_por_riesgo():
    d = motor().evaluar(LARGO, REGLAS, CUENTA)
    assert d.aprobada, d.rechazos
    o = d.orden
    # riesgo 0,5 % de 500 = 2,5 USDT; por unidad: 20 de stop + 1,99 de comisiones -> 0,1137 -> 0,113
    assert o.cantidad == D("0.113") and o.lado == "BUY" and o.apalancamiento == 1
    assert o.perdida_max_usdt <= D("2.5") and o.ganancia_neta_usdt >= D("1.5")


def test_aprueba_short():
    d = motor().evaluar(CORTO, REGLAS, CUENTA)
    assert d.aprobada and d.orden.lado == "SELL" and d.orden.objetivo < d.orden.precio_ref < d.orden.stop


def test_stop_muy_cercano_nunca_supera_2x():
    d = motor().evaluar(replace(LARGO, stop=D("1999"), objetivo=D("2010")), REGLAS, CUENTA)
    assert d.aprobada, d.rechazos
    assert d.orden.apalancamiento <= 2 and d.orden.nocional_usdt <= D(1000)


def test_config_saltandose_validacion_no_pasa_de_2x():
    validos = Config(**BASE).model_dump()
    cfg = Config.model_construct(**{**validos, "apalancamiento_max": D(10)})   # se salta el validador
    m = MotorRiesgo(cfg, D("0.05"))
    assert m.apalancamiento_max == 2
    d = m.evaluar(LARGO, REGLAS, CUENTA)
    assert not d.aprobada and any("límite rígido" in x for x in d.rechazos)


def test_modo_real_bloqueado():
    d = motor(modo="real").evaluar(LARGO, REGLAS, CUENTA)
    assert not d.aprobada and any("modo real" in x for x in d.rechazos)


def test_datos_no_aptos():
    d = motor().evaluar(LARGO, REGLAS, CUENTA, datos_aptos=False, motivos_calidad=("libro: cruzado",))
    assert not d.aprobada and "datos NO APTOS: libro: cruzado" in d.rechazos


def test_sin_senal():
    d = motor().evaluar(Senal("ETHUSDT", NINGUNA, 0), REGLAS, CUENTA)
    assert not d.aprobada and d.rechazos == ["no hay señal de entrada"]


def test_stop_obligatorio():
    d = motor().evaluar(replace(LARGO, stop=None), REGLAS, CUENTA)
    assert not d.aprobada and any("stop obligatorio" in x for x in d.rechazos)


def test_stop_del_lado_equivocado():
    d = motor().evaluar(replace(LARGO, stop=D("2010")), REGLAS, CUENTA)
    assert not d.aprobada and any("lado correcto" in x for x in d.rechazos)


def test_simbolo_o_direccion_no_permitidos():
    assert not motor(mercados=["BTCUSDT"]).evaluar(LARGO, REGLAS, CUENTA).aprobada
    d = motor(direcciones=["LONG"]).evaluar(CORTO, REGLAS, CUENTA)
    assert not d.aprobada and any("SHORT no permitida" in x for x in d.rechazos)


def test_limite_de_perdida_diaria_bloquea_entradas():
    d = motor().evaluar(LARGO, REGLAS, EstadoCuenta(D(485), pnl_dia_usdt=D(-15)))   # 3 % de 500 = 15
    assert not d.aprobada and len(d.rechazos) == 1 and "pérdida diaria" in d.rechazos[0]


def test_riesgo_no_supera_lo_que_queda_del_dia():
    d = motor().evaluar(LARGO, REGLAS, EstadoCuenta(D(486), pnl_dia_usdt=D(-14)))   # queda 1 USDT
    assert not d.aprobada or d.orden.perdida_max_usdt <= D(1)


def test_sin_martingala_el_riesgo_baja_tras_perdidas_y_no_sube_tras_ganancias():
    normal = motor().evaluar(LARGO, REGLAS, CUENTA).orden
    tras_perdidas = motor().evaluar(LARGO, REGLAS, EstadoCuenta(D(400))).orden
    tras_ganancias = motor().evaluar(LARGO, REGLAS, EstadoCuenta(D(800))).orden
    assert tras_perdidas.cantidad < normal.cantidad
    assert tras_ganancias.cantidad == normal.cantidad


def test_maximo_de_posiciones_y_sin_promediar():
    abierta = EstadoCuenta(D(500), posiciones=(PosicionAbierta("ETHUSDT", LONG, D(200)),))
    d = motor().evaluar(LARGO, REGLAS, abierta)
    assert not d.aprobada
    assert any("máximo 1" in x for x in d.rechazos) and any("no se promedia" in x for x in d.rechazos)


def test_exposicion_cuenta_posiciones_abiertas():
    abierta = EstadoCuenta(D(500), posiciones=(PosicionAbierta("BTCUSDT", LONG, D(900)),))
    d = motor(posiciones_abiertas_max=2).evaluar(replace(LARGO, stop=D("1999"), objetivo=D("2040")), REGLAS, abierta)
    assert d.aprobada and d.orden.nocional_usdt <= D(100)        # quedan 1000 - 900 de exposición


def test_bajo_el_minimo_del_exchange():
    d = motor().evaluar(LARGO, replace(REGLAS, nocional_min=D(5000)), CUENTA)
    assert not d.aprobada and any("mínimo del exchange" in x for x in d.rechazos)


def test_ganancia_neta_insuficiente_por_comisiones():
    d = motor().evaluar(replace(LARGO, objetivo=D("2005")), REGLAS, CUENTA)
    assert not d.aprobada and any("ganancia neta estimada" in x for x in d.rechazos)


def test_stop_cerca_de_liquidacion():
    reglas = replace(REGLAS, nocional_min=D(1))
    d = motor().evaluar(replace(LARGO, stop=D("1000"), objetivo=D("4000")), reglas, CUENTA)
    assert not d.aprobada and any("liquidación" in x for x in d.rechazos)


def test_redondeo_conservador_al_tick():
    reglas = replace(REGLAS, tick_precio=D("0.5"))
    o = motor().evaluar(replace(LARGO, stop=D("1980.3"), objetivo=D("2040.3")), reglas, CUENTA).orden
    assert o.stop == D("1980.5") and o.objetivo == D("2040.0")      # stop más cerca, objetivo más modesto


@pytest.mark.parametrize("senal", [LARGO, CORTO])
def test_misma_entrada_misma_decision(senal):
    assert motor().evaluar(senal, REGLAS, CUENTA) == motor().evaluar(senal, REGLAS, CUENTA)


def test_salida_maker_en_el_objetivo_baja_las_comisiones():
    taker = motor().evaluar(LARGO, REGLAS, CUENTA).orden
    maker = MotorRiesgo(Config(**BASE), D("0.05"), D("0.02")).evaluar(LARGO, REGLAS, CUENTA).orden
    assert maker.cantidad == taker.cantidad and maker.perdida_max_usdt == taker.perdida_max_usdt   # el stop sigue taker
    assert maker.comisiones_usdt == D("0.113") * (D("2000") * D("0.0005") + D("2040") * D("0.0002"))
    assert maker.ganancia_neta_usdt > taker.ganancia_neta_usdt
