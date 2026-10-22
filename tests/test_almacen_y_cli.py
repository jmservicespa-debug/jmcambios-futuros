import json

from futuros.data import cli
from futuros.data.almacen import Almacen
from futuros.data.rest import ClienteREST
from futuros.data.ws import parsear_mensaje
from simulado import AHORA_MS, BASE_VELA, ConexionFalsa, transporte, ws_depth, ws_kline, ws_mark


def test_almacen_guarda_y_no_duplica_velas(tmp_path):
    a = Almacen(tmp_path / "data" / "m.sqlite")
    v1 = parsear_mensaje(ws_kline(c="100.5"))
    v2 = parsear_mensaje(ws_kline(c="100.7"))          # misma vela, precio actualizado
    a.guardar_velas([v1]); a.guardar_velas([v2])
    a.guardar_libro(parsear_mensaje(ws_depth()))
    a.guardar_mark(parsear_mensaje(ws_mark()))
    a.guardar_calidad("BTCUSDT", AHORA_MS, False, ["libro: vacío"])
    assert a.contar("velas") == 1 and a.contar("libros") == 1 and a.contar("mark_price") == 1
    assert a.db.execute("SELECT cierre FROM velas").fetchone()[0] == "100.7"
    assert json.loads(a.db.execute("SELECT motivos FROM calidad").fetchone()[0]) == ["libro: vacío"]
    a.close()


def test_estado_reemplaza_vela_en_curso_y_agrega_nueva():
    est = cli.Estado(["BTCUSDT"])
    est.agregar_vela(parsear_mensaje(ws_kline(c="1")))
    est.agregar_vela(parsear_mensaje(ws_kline(c="2")))
    est.agregar_vela(parsear_mensaje(ws_kline(apertura=BASE_VELA + 60_000, c="3")))
    assert [str(v.cierre) for v in est.velas["BTCUSDT"]] == ["2", "3"]


def _cliente():
    return ClienteREST(transport=transporte(), reloj=lambda: AHORA_MS / 1000)


def test_comando_solo_rest(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    db = tmp_path / "m.sqlite"
    assert cli.main(["--solo-rest", "--db", str(db)], cliente=_cliente()) == 0
    out = capsys.readouterr().out
    assert "BTCUSDT" in out and "ETHUSDT" in out and "APTO" in out
    a = Almacen(db)
    assert a.contar("velas") == 200 and a.contar("mark_price") == 2
    a.close()


def test_comando_con_websocket_simulado(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    db = tmp_path / "m.sqlite"

    def conectar(url):
        if "/market/" in url:
            return ConexionFalsa([ws_kline(), ws_mark(), ws_kline("ETHUSDT"), ws_mark("ETHUSDT")], quedarse_abierta=True)
        return ConexionFalsa([ws_depth(), ws_depth("ETHUSDT")], quedarse_abierta=True)

    assert cli.main(["--segundos", "1", "--db", str(db)], cliente=_cliente(), conectar=conectar) == 0
    out = capsys.readouterr().out
    assert "Mensajes WebSocket recibidos: 6" in out
    assert "[WebSocket market] conectado" in out and "[WebSocket public] conectado" in out
    resumen = out.split("=== Resumen final ===")[1]
    assert "caída" not in resumen and resumen.count("APTO para operar") == 2 and "NO APTO" not in resumen


def test_comando_sin_internet_da_mensaje_claro(tmp_path, capsys):
    import httpx

    def sin_red(req):
        raise httpx.ConnectError("sin red")

    c = ClienteREST(transport=httpx.MockTransport(sin_red))
    assert cli.main(["--solo-rest", "--db", str(tmp_path / "m.sqlite")], cliente=c) == 1
    assert "sin conexión con Binance" in capsys.readouterr().err
