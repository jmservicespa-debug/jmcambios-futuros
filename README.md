# jmcambios-futuros

Agente de trading de futuros (Binance USDⓈ-M) **en construcción**. Hoy: Fase 1 (diseño y configuración).
Arranca en modo simulación; apalancamiento máximo 2x fijo. Ver `docs/DISENO.md`.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```
