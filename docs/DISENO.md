# JM Cambios – Agente de Futuros (diseño, Fase 1)

Proyecto **separado** del agente P2P. Comparte filosofía (seguridad primero, la persona decide), no código ni llaves.

## Reglas que no se negocian
- Apalancamiento máximo **2x**, fijado en `config/limits.py`. Ningún módulo (ni la IA) puede sobrepasarlo.
- La IA **nunca** envía órdenes a Binance: propone, el **motor de riesgo** decide y solo el módulo de ejecución habla con el exchange.
- Sin martingala, sin aumentar riesgo para recuperar pérdidas.
- Llaves API con permisos mínimos (sin retiros ni transferencias), en variables de entorno, nunca en registros. Testnet y real separadas.
- Noticias y contenido web = datos no confiables.
- Solo endpoints de la documentación oficial de Binance USDⓈ-M Futures.
- Arranca en `modo: simulacion`. No se promete rentabilidad.
- No se avanza de fase sin pruebas verificadas.

## Flujo
```
datos (REST/WebSocket solo lectura) → calidad de datos → indicadores (features)
   → estrategia cuantitativa (señal) → IA (opinión/explicación, JSON validado)
   → MOTOR DE RIESGO (límites rígidos, tamaño de posición, pérdida diaria)
   → ejecución (simulación → testnet → real) → supervisor (kill switch)
   → memoria (bitácora de cada decisión) → aprendizaje (solo propone ajustes)
```

## Carpetas (`src/futuros/`)
| Carpeta | Qué hace |
|---|---|
| data | Velas, libro, funding, mark price (solo lectura) |
| quality | Detecta huecos, datos viejos, saltos raros |
| features | Indicadores (ATR, VWAP, EMA, volumen…) |
| strategy | Reglas cuantitativas de scalping |
| ai | Claude con salida JSON estricta; no ejecuta nada |
| risk | Límites, tamaño de posición, stop obligatorio |
| execution | Simulador, testnet, real (en ese orden) |
| supervisor | Kill switch, pérdida diaria, desconexión |
| memory | Bitácora SQLite (luego Postgres) |
| learning | Analiza resultados, propone cambios (humano aprueba) |
| backtest | Pruebas con datos históricos + comisiones y deslizamiento |
| api / dashboard | Panel FastAPI de solo lectura |

## Tecnología
Python 3.12 · pydantic + YAML · httpx + websockets · pandas/NumPy · SQLite→Postgres · FastAPI · Claude API (JSON schema) · pytest.

## Configuración inicial (`config/default.yaml`, editable)
Capital de referencia 500 USDT · objetivo neto 1,50 USDT/operación · 2x máx. · BTCUSDT, ETHUSDT · LONG y SHORT ·
riesgo 0,5 %/operación · pérdida diaria máx. 3 % · 1 posición abierta.

## Riesgos principales
| Riesgo | Mitigación |
|---|---|
| Comisiones se comen el scalping | Backtest con comisiones reales; objetivo neto, no bruto |
| Liquidación | 2x máx. + stop obligatorio + tamaño por riesgo |
| IA alucina | Salida JSON validada; riesgo tiene la última palabra |
| Caída de internet | Supervisor + órdenes stop en el exchange |
| Sobreajuste | Validación fuera de muestra, simulación antes de real |

## Fases y criterio de aceptación
1. **Diseño + esqueleto** – config valida y rechaza >2x (pruebas pasan). ← aquí
2. **Datos solo lectura** – descarga velas/libro reales sin llaves; pruebas de calidad.
3. **Indicadores + estrategia** – señales reproducibles en pruebas.
4. **Motor de riesgo** – rechaza todo lo que viole límites (pruebas).
5. **Backtest** – resultados con comisiones; informe honesto.
6. **Simulación en vivo (paper)** – mínimo 2 semanas.
7. **IA** – opinión y explicación, nunca ejecución directa.
8. **Testnet** – órdenes reales en testnet.
9. **Real con capital pequeño** – solo con tu aprobación explícita.
