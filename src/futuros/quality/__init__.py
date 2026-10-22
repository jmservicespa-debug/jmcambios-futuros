"""Calidad de datos: marca los datos como no aptos para operar si algo falla."""
from futuros.quality.verificador import MonitorConexion, Resultado, Umbrales, evaluar

__all__ = ["MonitorConexion", "Resultado", "Umbrales", "evaluar"]
