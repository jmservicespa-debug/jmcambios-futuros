"""Guardado local simple en SQLite (carpeta data/, ignorada por git).

Precios como texto para no perder decimales. Las velas se guardan por clave
(símbolo, intervalo, apertura): si llega de nuevo la misma vela, se actualiza.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from futuros.data.modelos import Libro, MarkPrice, Vela

RUTA_POR_DEFECTO = Path("data") / "mercado.sqlite"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS velas (
    simbolo TEXT NOT NULL, intervalo TEXT NOT NULL, apertura_ms INTEGER NOT NULL, cierre_ms INTEGER NOT NULL,
    apertura TEXT NOT NULL, maximo TEXT NOT NULL, minimo TEXT NOT NULL, cierre TEXT NOT NULL, volumen TEXT NOT NULL,
    cerrada INTEGER NOT NULL, PRIMARY KEY (simbolo, intervalo, apertura_ms));
CREATE TABLE IF NOT EXISTS libros (
    simbolo TEXT NOT NULL, ts_ms INTEGER NOT NULL, ultimo_update_id INTEGER NOT NULL,
    mejor_bid TEXT, mejor_ask TEXT, bids TEXT NOT NULL, asks TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mark_price (
    simbolo TEXT NOT NULL, ts_ms INTEGER NOT NULL, mark TEXT NOT NULL, indice TEXT NOT NULL,
    funding TEXT NOT NULL, proximo_funding_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS calidad (
    simbolo TEXT NOT NULL, ts_ms INTEGER NOT NULL, apto INTEGER NOT NULL, motivos TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_libros ON libros (simbolo, ts_ms);
CREATE INDEX IF NOT EXISTS idx_mark ON mark_price (simbolo, ts_ms);
"""


class Almacen:
    def __init__(self, ruta: str | Path = RUTA_POR_DEFECTO):
        ruta = Path(ruta)
        if str(ruta) != ":memory:":
            ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta = ruta
        self.db = sqlite3.connect(ruta)
        self.db.executescript(_ESQUEMA)

    def close(self) -> None:
        self.db.close()

    def guardar_velas(self, velas: list[Vela]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO velas VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(v.simbolo, v.intervalo, v.apertura_ms, v.cierre_ms, str(v.apertura), str(v.maximo), str(v.minimo),
              str(v.cierre), str(v.volumen), int(v.cerrada)) for v in velas])
        self.db.commit()

    def guardar_libro(self, lb: Libro, niveles: int = 5) -> None:
        def a_txt(lado):
            return json.dumps([[str(p), str(q)] for p, q in lado[:niveles]])
        self.db.execute("INSERT INTO libros VALUES (?,?,?,?,?,?,?)",
                        (lb.simbolo, lb.ts_ms, lb.ultimo_update_id, str(lb.mejor_bid), str(lb.mejor_ask),
                         a_txt(lb.bids), a_txt(lb.asks)))
        self.db.commit()

    def guardar_mark(self, mp: MarkPrice) -> None:
        self.db.execute("INSERT INTO mark_price VALUES (?,?,?,?,?,?)",
                        (mp.simbolo, mp.ts_ms, str(mp.mark), str(mp.indice), str(mp.funding), mp.proximo_funding_ms))
        self.db.commit()

    def guardar_calidad(self, simbolo: str, ts_ms: int, apto: bool, motivos: list[str]) -> None:
        self.db.execute("INSERT INTO calidad VALUES (?,?,?,?)",
                        (simbolo, ts_ms, int(apto), json.dumps(motivos, ensure_ascii=False)))
        self.db.commit()

    def contar(self, tabla: str, simbolo: str | None = None) -> int:
        if tabla not in ("velas", "libros", "mark_price", "calidad"):
            raise ValueError(tabla)
        if simbolo is None:
            return self.db.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        return self.db.execute(f"SELECT COUNT(*) FROM {tabla} WHERE simbolo=?", (simbolo,)).fetchone()[0]
