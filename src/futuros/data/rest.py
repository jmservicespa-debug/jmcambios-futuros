"""Cliente REST público de solo lectura (sin llaves API).

Respeta los límites de peso de Binance:
- lee la cabecera X-MBX-USED-WEIGHT-1M de cada respuesta;
- se pone un tope propio, muy por debajo del límite de Binance;
- ante 429 (demasiadas solicitudes) o 418 (IP bloqueada) se detiene y avisa;
  nunca reintenta en bucle ni intenta eludir el control.
"""
from __future__ import annotations

import re
import time
from decimal import Decimal

import httpx

from futuros.data import endpoints as ep
from futuros.data.modelos import Funding, Libro, MarkPrice, Vela

TOPE_PESO_POR_MINUTO = 600   # propio y conservador; Binance permite bastante más por IP
_SIMBOLO = re.compile(r"^[A-Z0-9]{5,20}$")


class ErrorDatos(Exception):
    """Error al pedir datos de mercado."""


class LimiteBinance(ErrorDatos):
    """Binance respondió 429: hay que esperar `reintentar_en` segundos antes de volver a pedir."""

    def __init__(self, mensaje: str, reintentar_en: int | None):
        super().__init__(mensaje)
        self.reintentar_en = reintentar_en


class IPBloqueada(LimiteBinance):
    """Binance respondió 418: la IP quedó bloqueada temporalmente por exceso de solicitudes."""


class PresupuestoPesoAgotado(ErrorDatos):
    """Nuestro tope propio de peso por minuto se alcanzó; no se envía la solicitud."""


def validar_simbolo(simbolo: str) -> str:
    s = simbolo.strip().upper()
    if not _SIMBOLO.match(s):
        raise ValueError(f"símbolo inválido: {simbolo!r}")
    return s


class ClienteREST:
    def __init__(self, base_url: str = ep.REST_BASE, timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None, tope_peso: int = TOPE_PESO_POR_MINUTO,
                 reloj=time.time):
        # Sin cabeceras de autenticación: este cliente no sabe usar llaves.
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport,
                                  headers={"User-Agent": "jmcambios-futuros/solo-lectura"})
        self.tope_peso = tope_peso
        self._reloj = reloj
        self.peso_usado: int = 0          # último valor informado por Binance (o estimado)
        self._minuto: int = -1

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- núcleo ---------------------------------------------------------------
    def _get(self, ruta: str, params: dict, peso: int):
        minuto = int(self._reloj() // 60)
        if minuto != self._minuto:
            self._minuto, self.peso_usado = minuto, 0
        if self.peso_usado + peso > self.tope_peso:
            raise PresupuestoPesoAgotado(
                f"tope propio de {self.tope_peso} de peso/minuto alcanzado ({self.peso_usado} usado); espera al próximo minuto")
        try:
            r = self._http.get(ruta, params=params)
        except httpx.HTTPError as e:
            raise ErrorDatos(f"sin conexión con Binance ({type(e).__name__}: {e})") from e

        usado = r.headers.get("X-MBX-USED-WEIGHT-1M") or r.headers.get("x-mbx-used-weight-1m")
        self.peso_usado = int(usado) if usado and usado.isdigit() else self.peso_usado + peso

        if r.status_code in (418, 429):
            ra = r.headers.get("Retry-After")
            espera = int(ra) if ra and ra.isdigit() else None
            cls = IPBloqueada if r.status_code == 418 else LimiteBinance
            raise cls(f"Binance pidió esperar (HTTP {r.status_code}); reintentar en {espera or '?'} s", espera)
        if r.status_code != 200:
            raise ErrorDatos(f"HTTP {r.status_code} en {ruta}: {r.text[:200]}")
        return r.json()

    # --- endpoints ------------------------------------------------------------
    def hora_servidor_ms(self) -> int:
        return int(self._get(ep.TIEMPO, {}, 1)["serverTime"])

    def velas(self, simbolo: str, intervalo: str = "1m", limit: int = 100) -> list[Vela]:
        simbolo = validar_simbolo(simbolo)
        if intervalo not in ep.INTERVALOS_MS:
            raise ValueError(f"intervalo no soportado: {intervalo}")
        if not 1 <= limit <= ep.VELAS_LIMITE_MAX:
            raise ValueError(f"limit debe estar entre 1 y {ep.VELAS_LIMITE_MAX}")
        datos = self._get(ep.VELAS, {"symbol": simbolo, "interval": intervalo, "limit": limit}, ep.peso_velas(limit))
        ahora = int(self._reloj() * 1000)
        return [Vela(simbolo, intervalo, int(k[0]), int(k[6]), Decimal(k[1]), Decimal(k[2]), Decimal(k[3]),
                     Decimal(k[4]), Decimal(k[5]), cerrada=int(k[6]) < ahora) for k in datos]

    def libro(self, simbolo: str, limit: int = 20) -> Libro:
        simbolo = validar_simbolo(simbolo)
        if limit not in ep.LIMITES_LIBRO:
            raise ValueError(f"limit del libro debe ser uno de {ep.LIMITES_LIBRO}")
        d = self._get(ep.LIBRO, {"symbol": simbolo, "limit": limit}, ep.peso_libro(limit))
        return Libro(simbolo, int(d.get("E") or d.get("T") or 0), int(d["lastUpdateId"]),
                     [(Decimal(p), Decimal(q)) for p, q in d["bids"]],
                     [(Decimal(p), Decimal(q)) for p, q in d["asks"]])

    def mark_price(self, simbolo: str) -> MarkPrice:
        simbolo = validar_simbolo(simbolo)
        d = self._get(ep.MARK_PRICE, {"symbol": simbolo}, ep.peso_mark_price(True))
        return MarkPrice(simbolo, int(d["time"]), Decimal(d["markPrice"]), Decimal(d["indexPrice"]),
                         Decimal(d["lastFundingRate"]), int(d["nextFundingTime"]))

    def historial_funding(self, simbolo: str, limit: int = 5) -> list[Funding]:
        simbolo = validar_simbolo(simbolo)
        if not 1 <= limit <= 1000:
            raise ValueError("limit debe estar entre 1 y 1000")
        datos = self._get(ep.FUNDING, {"symbol": simbolo, "limit": limit}, 1)
        return [Funding(simbolo, int(f["fundingTime"]), Decimal(f["fundingRate"])) for f in datos]
