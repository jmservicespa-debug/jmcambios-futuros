"""Carga y valida la configuración editable contra los límites rígidos."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from config import limits


class Config(BaseModel):
    capital_referencia_usdt: Decimal = Field(gt=0)
    objetivo_neto_por_operacion_usdt: Decimal = Field(gt=0)
    apalancamiento_max: Decimal = Field(gt=0)
    mercados: list[str]
    direcciones: list[str]
    modo: str
    riesgo_por_operacion_pct: Decimal = Field(gt=0)
    perdida_diaria_max_pct: Decimal = Field(gt=0)
    exposicion_max_pct: Decimal = Field(gt=0)
    posiciones_abiertas_max: int = Field(ge=1)

    @field_validator("apalancamiento_max")
    @classmethod
    def _apalancamiento(cls, v: Decimal) -> Decimal:
        if v > limits.APALANCAMIENTO_MAX:
            raise ValueError(f"apalancamiento {v}x supera el límite rígido de {limits.APALANCAMIENTO_MAX}x")
        return v

    @field_validator("riesgo_por_operacion_pct")
    @classmethod
    def _riesgo(cls, v: Decimal) -> Decimal:
        if v > limits.RIESGO_POR_OPERACION_MAX_PCT:
            raise ValueError(f"riesgo por operación {v} % supera el máximo de {limits.RIESGO_POR_OPERACION_MAX_PCT} %")
        return v

    @field_validator("perdida_diaria_max_pct")
    @classmethod
    def _perdida(cls, v: Decimal) -> Decimal:
        if v > limits.PERDIDA_DIARIA_MAX_PCT:
            raise ValueError(f"pérdida diaria {v} % supera el máximo de {limits.PERDIDA_DIARIA_MAX_PCT} %")
        return v

    @field_validator("modo")
    @classmethod
    def _modo(cls, v: str) -> str:
        if v not in limits.MODOS:
            raise ValueError(f"modo inválido: {v} (permitidos: {', '.join(limits.MODOS)})")
        return v

    @field_validator("direcciones")
    @classmethod
    def _dirs(cls, v: list[str]) -> list[str]:
        if not v or any(d not in ("LONG", "SHORT") for d in v):
            raise ValueError("direcciones permitidas: LONG y/o SHORT")
        return v

    @model_validator(mode="after")
    def _coherencia(self) -> "Config":
        if self.posiciones_abiertas_max > limits.POSICIONES_ABIERTAS_MAX:
            raise ValueError(f"posiciones abiertas máx. {limits.POSICIONES_ABIERTAS_MAX}")
        if self.exposicion_max_pct > self.apalancamiento_max * 100:
            raise ValueError("la exposición máxima no puede superar capital × apalancamiento máximo")
        return self


def load(path: str | Path = "config/default.yaml") -> Config:
    return Config(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))
