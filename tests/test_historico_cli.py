from decimal import Decimal

import httpx
import pytest

from futuros.backtest import historico
from futuros.backtest.cli import main_backtest, main_historico
from futuros.data.almacen import Almacen
from futuros.data.rest import ClienteREST, LimiteBinance
from simulado import AHORA_MS, exchange_info

P = 300_000


def mercado(pedidos, estado=200, reloj=None):
    """Binance simulado: velas de 5m con precio en zigzag desde startTime hasta AHORA_MS."""
    def manejar(req):
        ruta = req.url.path
        if estado != 200:
            return httpx.Response(estado, headers={"Retry-After": "60"}, json={})
        if ruta == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json=exchange_info())
        pedidos.append(dict(req.url.params))
        inicio = int(req.url.params["startTime"]) // P * P
        limit = int(req.url.params["limit"])
        filas = []
        for k in range(limit):
            t = inicio + k * P
            if t > AHORA_MS:
                break
            c = 2000 + (t // P) % 50 - 25
            filas.append([t, str(c), str(c + 2), str(c - 2), str(c), "10", t + P - 1, "0", 1, "0", "0", "0"])
        return httpx.Response(200, headers={"X-MBX-USED-WEIGHT-1M": "7"}, json=filas)
    return ClienteREST(transport=httpx.MockTransport(manejar), reloj=reloj or (lambda: AHORA_MS / 1000))


def test_descarga_por_bloques_y_retoma(tmp_path):
    pedidos = []
    a = Almacen(tmp_path / "m.sqlite")
    n = historico.descargar(mercado(pedidos), a, "ETHUSDT", "5m", 10, ahora_ms=AHORA_MS, avisar=lambda m: None)
    assert n == 10 * 288 - 1 or n == 10 * 288           # velas cerradas en 10 días
    assert len(pedidos) == 3 and all(p["limit"] == "1000" for p in pedidos)
    assert int(pedidos[1]["startTime"]) == int(pedidos[0]["startTime"]) + 1000 * P
    assert historico.huecos(a.leer_velas("ETHUSDT", "5m"), "5m") == []
    pedidos.clear()
    assert historico.descargar(mercado(pedidos), a, "ETHUSDT", "5m", 10, ahora_ms=AHORA_MS, avisar=lambda m: None) == 0
    a.close()


def test_espera_si_se_acaba_el_presupuesto_de_peso(tmp_path):
    reloj = [AHORA_MS / 1000]
    esperas = []

    def dormir(s):
        esperas.append(s)
        reloj[0] += 61

    c = mercado([], reloj=lambda: reloj[0])
    c.tope_peso = 10                                         # tras una solicitud (7 usados) no cabe otra de peso 5
    a = Almacen(tmp_path / "m.sqlite")
    n = historico.descargar(c, a, "ETHUSDT", "5m", 5, ahora_ms=AHORA_MS, dormir=dormir, avisar=lambda m: None)
    assert esperas and n >= 5 * 288 - 1
    a.close()


def test_429_detiene_la_descarga(tmp_path):
    a = Almacen(tmp_path / "m.sqlite")
    with pytest.raises(LimiteBinance):
        historico.descargar(mercado([], estado=429), a, "ETHUSDT", "5m", 5, ahora_ms=AHORA_MS, avisar=lambda m: None)
    a.close()


def test_huecos_detecta_tramos_faltantes():
    from futuros.data.modelos import Vela
    vs = [Vela("X", "5m", t * P, t * P + P - 1, *[Decimal(1)] * 5) for t in (0, 1, 4, 5)]
    assert historico.huecos(vs, "5m") == [(2 * P, 3 * P)]


def test_comandos_historico_y_backtest(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    db, rep = str(tmp_path / "m.sqlite"), tmp_path / "reports"
    assert main_historico(["--dias", "3", "--db", db], cliente=mercado([]), dormir=lambda s: None) == 0
    out = capsys.readouterr().out
    assert "BTCUSDT" in out and "ETHUSDT" in out and "sin huecos" in out
    assert main_backtest(["--dias", "3", "--db", db, "--reportes", str(rep)], cliente=mercado([])) == 0
    out = capsys.readouterr().out
    assert "Informe de backtest" in out and "No garantiza resultados futuros" in out
    assert len(list(rep.glob("backtest-*.md"))) == 1


def test_backtest_sin_datos_pide_descargar(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    assert main_backtest(["--db", str(tmp_path / "m.sqlite")], cliente=mercado([])) == 1
    assert "futuros-historico" in capsys.readouterr().err


def test_y_si_no_cambia_la_config(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    db = str(tmp_path / "m.sqlite")
    main_historico(["--dias", "3", "--db", db], cliente=mercado([]), dormir=lambda s: None)
    antes = open("config/default.yaml", encoding="utf-8").read()
    assert main_backtest(["--dias", "3", "--db", db, "--reportes", str(tmp_path), "--objetivo-neto", "0.5", "--objetivo-atr", "3"],
                         cliente=mercado([])) == 0
    out = capsys.readouterr().out
    assert "objetivo neto 0.5 USDT" in out and "objetivo a 3 ATR" in out
    assert open("config/default.yaml", encoding="utf-8").read() == antes


def test_intervalo_alternativo_solo_en_la_simulacion(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    db = str(tmp_path / "m.sqlite")
    assert main_backtest(["--dias", "3", "--db", db, "--intervalo", "15m"], cliente=mercado([])) == 1
    assert "futuros-historico --dias 3 --intervalo 15m" in capsys.readouterr().err
