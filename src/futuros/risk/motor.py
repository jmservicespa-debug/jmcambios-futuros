"""Motor de riesgo: la última palabra antes de cualquier orden.

Recibe una señal (de la estrategia o, más adelante, de la IA) y decide si se APRUEBA o se RECHAZA.
Si aprueba, entrega una OrdenPropuesta con tamaño, stop, objetivo y apalancamiento ya calculados.
Este módulo NO envía nada al exchange: solo el módulo de ejecución (fases futuras) podrá hacerlo,
y únicamente con una Decision aprobada por este motor.

Reglas (todas deben cumplirse; se informan TODOS los motivos de rechazo):
- Apalancamiento máximo 2x (config/limits.py), revisado otra vez aquí aunque la config ya lo valide.
- Modo real bloqueado hasta su fase y aprobación explícita.
- Datos APTOS, símbolo y dirección permitidos, stop OBLIGATORIO y del lado correcto.
- Pérdida diaria: al llegar al máximo no hay entradas nuevas, y una operación nunca puede arriesgar
  más de lo que queda del límite del día.
- Máximo de posiciones abiertas; nunca se abre otra posición en un símbolo que ya tiene una (sin promediar).
- Tamaño por riesgo: la pérdida si salta el stop (incluidas comisiones) no supera el % configurado
  del capital. La base es el MENOR entre capital de referencia y capital actual: tras pérdidas el riesgo
  baja, nunca sube (sin martingala).
- Exposición total ≤ capital × apalancamiento máximo; cantidades y precios redondeados a las reglas del exchange.
- Stop lejos de la zona de liquidación.
- Ganancia neta estimada en el objetivo (después de comisiones) ≥ objetivo neto configurado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from config import limits
from futuros.config import Config
from futuros.data.modelos import ReglasSimbolo
from futuros.strategy import LONG, SHORT, Senal

CIEN = Decimal(100)
MARGEN_LIQUIDACION = Decimal("0.5")   # el stop debe quedar a menos de la mitad de la distancia de liquidación


@dataclass(frozen=True)
class PosicionAbierta:
    simbolo: str
    direccion: str
    nocional_usdt: Decimal


@dataclass(frozen=True)
class EstadoCuenta:
    capital_usdt: Decimal                       # capital actual (equity)
    pnl_dia_usdt: Decimal = Decimal(0)          # resultado del día; negativo = pérdida
    posiciones: tuple[PosicionAbierta, ...] = ()


@dataclass(frozen=True)
class OrdenPropuesta:
    """Propuesta aprobada por el motor. NO es una orden enviada."""
    simbolo: str
    direccion: str
    lado: str                    # BUY | SELL
    cantidad: Decimal
    precio_ref: Decimal
    stop: Decimal
    objetivo: Decimal
    apalancamiento: int
    nocional_usdt: Decimal
    margen_usdt: Decimal
    perdida_max_usdt: Decimal    # si salta el stop, incluidas comisiones estimadas
    comisiones_usdt: Decimal     # entrada + salida en el objetivo
    ganancia_neta_usdt: Decimal  # en el objetivo, después de comisiones


@dataclass(frozen=True)
class Decision:
    aprobada: bool
    simbolo: str
    orden: OrdenPropuesta | None = None
    rechazos: list[str] = field(default_factory=list)


def _redondear(valor: Decimal, paso: Decimal, modo) -> Decimal:
    if paso <= 0:
        return valor
    return (valor / paso).to_integral_value(rounding=modo) * paso


class MotorRiesgo:
    def __init__(self, cfg: Config, comision_pct: Decimal):
        self.cfg = cfg
        self.comision = Decimal(comision_pct) / CIEN
        # Doble seguro: aunque alguien construya la config saltándose la validación, el 2x no se mueve.
        self.apalancamiento_max = min(Decimal(cfg.apalancamiento_max), limits.APALANCAMIENTO_MAX)

    def _rechazos_config(self) -> list[str]:
        c, r = self.cfg, []
        if c.apalancamiento_max > limits.APALANCAMIENTO_MAX:
            r.append(f"configuración pide {c.apalancamiento_max}x, sobre el límite rígido de {limits.APALANCAMIENTO_MAX}x")
        if c.riesgo_por_operacion_pct > limits.RIESGO_POR_OPERACION_MAX_PCT:
            r.append("riesgo por operación de la configuración sobre el límite rígido")
        if c.perdida_diaria_max_pct > limits.PERDIDA_DIARIA_MAX_PCT:
            r.append("pérdida diaria de la configuración sobre el límite rígido")
        if c.posiciones_abiertas_max > limits.POSICIONES_ABIERTAS_MAX:
            r.append("posiciones abiertas de la configuración sobre el límite rígido")
        if c.modo == "real":
            r.append("modo real bloqueado: requiere su fase y tu aprobación explícita")
        return r

    def evaluar(self, senal: Senal, reglas: ReglasSimbolo, cuenta: EstadoCuenta,
                datos_aptos: bool = True, motivos_calidad: tuple[str, ...] = ()) -> Decision:
        c, s = self.cfg, senal
        r = self._rechazos_config()
        if not datos_aptos:
            r.append("datos NO APTOS" + (": " + "; ".join(motivos_calidad) if motivos_calidad else ""))
        if s.direccion not in (LONG, SHORT):
            return Decision(False, s.simbolo, rechazos=r + ["no hay señal de entrada"])
        if s.simbolo not in c.mercados:
            r.append(f"{s.simbolo} no está en los mercados permitidos")
        if s.direccion not in c.direcciones:
            r.append(f"dirección {s.direccion} no permitida")
        if reglas.simbolo != s.simbolo:
            r.append("las reglas del exchange no corresponden al símbolo")
        if s.precio_ref is None or s.stop is None or s.objetivo is None:
            return Decision(False, s.simbolo, rechazos=r + ["stop obligatorio: la señal no trae precio, stop u objetivo"])

        # --- límites de cuenta -------------------------------------------------------------
        limite_dia = c.capital_referencia_usdt * c.perdida_diaria_max_pct / CIEN
        perdida_dia = max(Decimal(0), -cuenta.pnl_dia_usdt)
        if perdida_dia >= limite_dia:
            r.append(f"límite de pérdida diaria alcanzado ({perdida_dia:.2f} de {limite_dia:.2f} USDT): "
                     "no hay entradas nuevas hoy")
        if len(cuenta.posiciones) >= c.posiciones_abiertas_max:
            r.append(f"ya hay {len(cuenta.posiciones)} posición(es) abierta(s); máximo {c.posiciones_abiertas_max}")
        if any(p.simbolo == s.simbolo for p in cuenta.posiciones):
            r.append(f"ya hay una posición abierta en {s.simbolo} (no se promedia ni se aumenta)")
        capital = min(c.capital_referencia_usdt, cuenta.capital_usdt)
        if capital <= 0:
            return Decision(False, s.simbolo, rechazos=r + ["capital disponible en cero o negativo"])

        # --- precios redondeados al tick (siempre hacia el lado conservador) ----------------
        precio = s.precio_ref
        es_long = s.direccion == LONG
        stop = _redondear(s.stop, reglas.tick_precio, ROUND_CEILING if es_long else ROUND_FLOOR)
        objetivo = _redondear(s.objetivo, reglas.tick_precio, ROUND_FLOOR if es_long else ROUND_CEILING)
        if not ((stop < precio < objetivo) if es_long else (objetivo < precio < stop)):
            return Decision(False, s.simbolo, rechazos=r + [
                f"stop {stop} / objetivo {objetivo} no están del lado correcto del precio {precio}"])
        distancia = abs(precio - stop)

        # --- tamaño de la posición ---------------------------------------------------------------
        riesgo_max = min(capital * c.riesgo_por_operacion_pct / CIEN, limite_dia - perdida_dia)
        if riesgo_max <= 0:          # ya se informó el límite diario; no hay riesgo disponible para calcular tamaño
            return Decision(False, s.simbolo, rechazos=r)
        costo_unidad = (precio + stop) * self.comision          # comisión de entrada + salida en el stop
        cant_riesgo = riesgo_max / (distancia + costo_unidad)
        exposicion = min(self.apalancamiento_max, c.exposicion_max_pct / CIEN)
        nocional_libre = capital * exposicion - sum((p.nocional_usdt for p in cuenta.posiciones), Decimal(0))
        cant_exposicion = max(Decimal(0), nocional_libre) / precio
        cantidad = _redondear(min(cant_riesgo, cant_exposicion, reglas.cantidad_max),
                              reglas.paso_cantidad, ROUND_FLOOR)
        nocional = cantidad * precio
        if cantidad < reglas.cantidad_min or nocional < reglas.nocional_min:
            r.append(f"con el capital y el riesgo configurados la cantidad ({cantidad}) queda bajo el mínimo "
                     f"del exchange (cantidad mín. {reglas.cantidad_min}, nocional mín. {reglas.nocional_min} USDT)")
            return Decision(False, s.simbolo, rechazos=r)

        apalancamiento = max(1, int((nocional / capital).to_integral_value(rounding=ROUND_CEILING)))
        if apalancamiento > self.apalancamiento_max:
            r.append(f"necesitaría {apalancamiento}x, sobre el máximo de {self.apalancamiento_max}x")
        distancia_liq_pct = CIEN / apalancamiento
        if distancia / precio * CIEN >= distancia_liq_pct * MARGEN_LIQUIDACION:
            r.append(f"stop demasiado lejos ({distancia / precio * CIEN:.2f} %): muy cerca de la zona de liquidación")

        perdida_max = cantidad * (distancia + costo_unidad)
        comisiones = cantidad * (precio + objetivo) * self.comision
        neta = cantidad * abs(objetivo - precio) - comisiones
        if neta < c.objetivo_neto_por_operacion_usdt:
            r.append(f"ganancia neta estimada {neta:.2f} USDT (después de {comisiones:.2f} USDT de comisiones) "
                     f"menor al objetivo de {c.objetivo_neto_por_operacion_usdt} USDT")
        if r:
            return Decision(False, s.simbolo, rechazos=r)

        orden = OrdenPropuesta(s.simbolo, s.direccion, "BUY" if es_long else "SELL", cantidad, precio, stop, objetivo,
                               apalancamiento, nocional, nocional / apalancamiento, perdida_max, comisiones, neta)
        return Decision(True, s.simbolo, orden=orden)
