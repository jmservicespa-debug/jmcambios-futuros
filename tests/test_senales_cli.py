from futuros.config import load
from futuros.data.almacen import Almacen
from futuros.data.rest import ClienteREST
from futuros.strategy import EstrategiaConfig
from futuros.strategy.cli import cargar_config, main
from simulado import AHORA_MS, transporte

PASO = 300_000
BASE5 = (AHORA_MS // PASO) * PASO


def klines_5m(n=200):
    out = []
    for i in range(n):
        t = BASE5 - (n - 1 - i) * PASO
        out.append([t, "100.4", "100.6", "100.3", "100.5", "10", t + PASO - 1, "1000", 50, "5", "500", "0"])
    return out


def test_config_por_defecto_tiene_estrategia_y_sigue_validando_limites():
    cfg, direcciones = cargar_config("config/default.yaml")
    assert cfg.intervalo == "5m" and cfg.ema_rapida == 9 and direcciones == ("LONG", "SHORT")
    assert load().apalancamiento_max == 2          # la sección nueva no rompe la Fase 1
    assert cargar_config("no-existe.yaml")[0] == EstrategiaConfig()


def test_comando_senales_guarda_sin_duplicar(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("time.time", lambda: AHORA_MS / 1000)
    db = tmp_path / "m.sqlite"
    c = ClienteREST(transport=transporte(ajustes={"/fapi/v1/klines": klines_5m()}), reloj=lambda: AHORA_MS / 1000)
    assert main(["--minutos", "2", "--db", str(db)], cliente=c, dormir=lambda s: None) == 0
    out = capsys.readouterr().out
    assert "NO se envía ninguna orden" in out
    assert out.count("SIN SEÑAL") == 4                  # 2 símbolos × 2 pasadas, serie plana = sin cruce
    a = Almacen(db)
    assert a.contar("senales") == 2                     # misma vela => no se duplica
    a.close()


def test_config_invalida_se_rechaza(tmp_path, capsys):
    malo = tmp_path / "c.yaml"
    malo.write_text("estrategia:\n  ema_rapida: 30\n  ema_lenta: 10\n", encoding="utf-8")
    try:
        main(["--config", str(malo), "--db", str(tmp_path / "m.sqlite")])
    except SystemExit as e:
        assert e.code == 2
    assert "configuración inválida" in capsys.readouterr().err
