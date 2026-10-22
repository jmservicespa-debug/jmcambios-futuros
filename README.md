# jmcambios-futuros

Agente de trading de futuros (Binance USDⓈ-M) **en construcción**. Hoy: Fase 3 (indicadores y señales de estrategia; sin llaves ni órdenes).
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
$env:FUTUROS_PRUEBA_REAL = "1"; pytest -q -m red   # prueba real opcional
```
