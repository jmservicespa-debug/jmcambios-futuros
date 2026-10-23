# jmcambios-futuros

Agente de trading de futuros (Binance USDⓈ-M) **en construcción**. Hoy: Fase 5 (backtest con datos históricos; sin llaves ni órdenes).
Arranca en modo simulación; apalancamiento máximo 2x fijo. Ver `docs/DISENO.md`.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

Ver datos reales (Windows / PowerShell):
```powershell
.venv\Scripts\Activate.ps1
futuros-datos               # REST + 60 s de WebSocket, BTCUSDT y ETHUSDT
futuros-datos --solo-rest   # solo la descarga inicial
futuros-senales             # señales de la estrategia (solo para estudiar)
futuros-riesgo --ejemplo    # decisiones del motor de riesgo (cuenta simulada)
futuros-historico --dias 90  # descarga velas históricas
futuros-backtest            # simula e informa (reports/)
$env:FUTUROS_PRUEBA_REAL = "1"; pytest -q -m red   # prueba real opcional
```
