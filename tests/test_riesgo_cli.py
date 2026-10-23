from futuros.data.rest import ClienteREST
from futuros.risk.cli import main
from simulado import AHORA_MS, exchange_info, transporte
from test_senales_cli import klines_5m


def cliente():
    return ClienteREST(transport=transporte(ajustes={"/fapi/v1/klines": klines_5m(),
                                                     "/fapi/v1/exchangeInfo": exchange_info()}),
                       reloj=lambda: AHORA_MS / 1000)


def test_comando_riesgo_con_ejemplos(capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    assert main(["--ejemplo"], cliente=cliente()) == 0
    out = capsys.readouterr().out
    assert "NO se envía ninguna orden" in out
    assert out.count("Señal actual: NINGUNA") == 2 and "no hay señal de entrada" in out
    assert out.count("Ejemplo HIPOTÉTICO LONG") == 2 and out.count("Ejemplo HIPOTÉTICO SHORT") == 2
    assert "APROBADA por el motor (propuesta, NO se envía)" in out


def test_comando_riesgo_con_perdida_diaria(capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    assert main(["--ejemplo", "--pnl-dia", "-15"], cliente=cliente()) == 0
    out = capsys.readouterr().out
    assert "APROBADA" not in out and "límite de pérdida diaria alcanzado" in out
