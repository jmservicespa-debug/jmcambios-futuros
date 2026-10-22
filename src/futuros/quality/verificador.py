"""Calidad de datos: decide si los datos de mercado son aptos para operar.

Regla simple: si cualquier revisión falla, el símbolo queda NO APTO y se listan los motivos.
Las fases siguientes (estrategia, riesgo) deben negarse a operar con datos no aptos.
Todas las horas son en milisegundos y en la hora de Binance (hora local + desfase medido).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from futuros.data.endpoints import INTERVALOS_MS
from futuros.data.modelos import Libro, MarkPrice, Vela


@dataclass(frozen=True)
class Umbrales:
    max_edad_mark_ms: int = 5_000          # mark price llega cada 1 s por WebSocket
    max_edad_libro_ms: int = 5_000         # libro llega cada 500 ms por WebSocket
    max_silencio_ms: int = 10_000          # sin mensajes de un stream por más de esto = desconectado
    salto_max_pct: Decimal = Decimal("3")  # cambio entre cierres de velas consecutivas
    rango_vela_max_pct: Decimal = Decimal("5")       # máximo-mínimo de una sola vela
    desvio_libro_mark_pct: Decimal = Decimal("0.5")  # precio medio del libro vs mark price
    desvio_mark_indice_pct: Decimal = Decimal("1")   # mark price vs precio índice
    desfase_reloj_max_ms: int = 2_000      # diferencia entre el reloj del PC y Binance


@dataclass
class Resultado:
    simbolo: str
    motivos: list[str] = field(default_factory=list)

    @property
    def apto(self) -> bool:
        return not self.motivos


def _pct(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b) / b * 100 if b else Decimal("Infinity")


def revisar_velas(velas: list[Vela], ahora_ms: int, u: Umbrales = Umbrales()) -> list[str]:
    if not velas:
        return ["velas: no hay datos"]
    paso = INTERVALOS_MS[velas[0].intervalo]
    m: list[str] = []
    huecos = 0
    for prev, v in zip(velas, velas[1:]):
        dif = v.apertura_ms - prev.apertura_ms
        if dif <= 0:
            m.append(f"velas: desordenadas o duplicadas en {v.apertura_ms}")
        elif dif != paso:
            huecos += dif // paso - 1 if dif % paso == 0 else 1
        if prev.cierre > 0 and _pct(v.cierre, prev.cierre) > u.salto_max_pct:
            m.append(f"velas: salto anormal de {_pct(v.cierre, prev.cierre):.2f} % en {v.apertura_ms}")
    if huecos:
        m.append(f"velas: faltan {huecos} vela(s) (huecos en la serie)")
    for v in velas:
        if v.minimo <= 0 or v.maximo < v.minimo or not (v.minimo <= v.apertura <= v.maximo) \
                or not (v.minimo <= v.cierre <= v.maximo):
            m.append(f"velas: valores incoherentes (OHLC) en {v.apertura_ms}")
        elif _pct(v.maximo, v.minimo) > u.rango_vela_max_pct:
            m.append(f"velas: rango anormal de {_pct(v.maximo, v.minimo):.2f} % en {v.apertura_ms}")
    ultima = velas[-1]
    if ahora_ms - ultima.apertura_ms > 2 * paso:
        m.append(f"velas: datos viejos (última vela de hace {(ahora_ms - ultima.apertura_ms) // 1000} s)")
    return m


def revisar_libro(libro: Libro | None, ahora_ms: int, mark: MarkPrice | None = None,
                  u: Umbrales = Umbrales()) -> list[str]:
    if libro is None or not libro.bids or not libro.asks:
        return ["libro: vacío o sin datos"]
    m: list[str] = []
    if libro.mejor_bid >= libro.mejor_ask:
        m.append(f"libro: cruzado (compra {libro.mejor_bid} >= venta {libro.mejor_ask})")
    edad = ahora_ms - libro.ts_ms
    if edad > u.max_edad_libro_ms:
        m.append(f"libro: datos viejos ({edad / 1000:.1f} s)")
    if mark is not None and libro.medio and _pct(libro.medio, mark.mark) > u.desvio_libro_mark_pct:
        m.append(f"libro: precio medio se aleja {_pct(libro.medio, mark.mark):.2f} % del mark price")
    return m


def revisar_mark(mark: MarkPrice | None, ahora_ms: int, u: Umbrales = Umbrales()) -> list[str]:
    if mark is None:
        return ["mark price: sin datos"]
    if mark.mark <= 0 or mark.indice <= 0:
        return ["mark price: valor inválido"]
    m: list[str] = []
    edad = ahora_ms - mark.ts_ms
    if edad > u.max_edad_mark_ms:
        m.append(f"mark price: datos viejos ({edad / 1000:.1f} s)")
    if _pct(mark.mark, mark.indice) > u.desvio_mark_indice_pct:
        m.append(f"mark price: se aleja {_pct(mark.mark, mark.indice):.2f} % del índice")
    return m


def revisar_reloj(desfase_ms: int, u: Umbrales = Umbrales()) -> list[str]:
    if abs(desfase_ms) > u.desfase_reloj_max_ms:
        return [f"reloj: tu PC está desfasado {desfase_ms / 1000:+.1f} s respecto de Binance (sincroniza la hora de Windows)"]
    return []


class MonitorConexion:
    """Sigue el estado de cada conexión WebSocket y el último mensaje por (símbolo, tipo)."""

    def __init__(self, u: Umbrales = Umbrales()):
        self.u = u
        self.conectado: dict[str, bool] = {}
        self.ultimo_motivo: dict[str, str] = {}
        self.desconexiones: dict[str, int] = {}
        self.ultimo_msg: dict[tuple[str, str], int] = {}

    def cambio_estado(self, nombre: str, conectado: bool, motivo: str) -> None:
        if self.conectado.get(nombre) and not conectado:
            self.desconexiones[nombre] = self.desconexiones.get(nombre, 0) + 1
        self.conectado[nombre] = conectado
        self.ultimo_motivo[nombre] = motivo

    def mensaje(self, simbolo: str, tipo: str, ahora_ms: int) -> None:
        self.ultimo_msg[(simbolo, tipo)] = ahora_ms

    def revisar(self, simbolo: str, tipos: list[str], ahora_ms: int) -> list[str]:
        m = [f"conexión '{n}' caída ({self.ultimo_motivo.get(n, '')})"
             for n, ok in self.conectado.items() if not ok]
        for t in tipos:
            ult = self.ultimo_msg.get((simbolo, t))
            if ult is None:
                m.append(f"{t}: aún no llega ningún mensaje")
            elif ahora_ms - ult > self.u.max_silencio_ms:
                m.append(f"{t}: sin mensajes hace {(ahora_ms - ult) / 1000:.0f} s")
        return m


def evaluar(simbolo: str, velas: list[Vela], libro: Libro | None, mark: MarkPrice | None,
            ahora_ms: int, desfase_ms: int = 0, monitor: MonitorConexion | None = None,
            tipos_ws: tuple[str, ...] = ("vela", "libro", "mark"), u: Umbrales = Umbrales()) -> Resultado:
    r = Resultado(simbolo)
    r.motivos += revisar_reloj(desfase_ms, u)
    r.motivos += revisar_velas(velas, ahora_ms, u)
    r.motivos += revisar_mark(mark, ahora_ms, u)
    r.motivos += revisar_libro(libro, ahora_ms, mark, u)
    if monitor is not None:
        r.motivos += monitor.revisar(simbolo, list(tipos_ws), ahora_ms)
    return r
