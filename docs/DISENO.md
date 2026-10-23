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
1. **Diseño + esqueleto** – config valida y rechaza >2x (pruebas pasan). ✔
2. **Datos solo lectura** – descarga velas/libro reales sin llaves; pruebas de calidad. ✔ (verificada en el PC: 44 pruebas pasan; datos reales de BTCUSDT y ETHUSDT APTOS)
3. **Indicadores + estrategia** – señales reproducibles en pruebas. ✔ (verificada en el PC: 70 pruebas pasan; futuros-senales funciona con datos reales)
4. **Motor de riesgo** – rechaza todo lo que viole límites (pruebas). ✔ (verificada en el PC: 94 pruebas pasan; freno de pérdida diaria y reglas reales de Binance comprobados)
5. **Backtest** – resultados con comisiones; informe honesto. ← aquí (falta correrlo con datos reales en el PC)
6. **Simulación en vivo (paper)** – mínimo 2 semanas.
7. **IA** – opinión y explicación, nunca ejecución directa.
8. **Testnet** – órdenes reales en testnet.
9. **Real con capital pequeño** – solo con tu aprobación explícita.

## Fase 2 – datos solo lectura (detalle)
Fuentes (documentación oficial USDⓈ-M, sin llaves):
| Dato | REST (`https://fapi.binance.com`) | WebSocket (`wss://fstream.binance.com`) |
|---|---|---|
| Hora del servidor | `GET /fapi/v1/time` (peso 1) | – |
| Velas | `GET /fapi/v1/klines` (peso 1–10 según `limit`) | `/market` · `<simbolo>@kline_1m` |
| Libro | `GET /fapi/v1/depth` (peso 2 con `limit` ≤ 50) | `/public` · `<simbolo>@depth20@500ms` |
| Mark price + funding | `GET /fapi/v1/premiumIndex` (peso 1 con `symbol`) | `/market` · `<simbolo>@markPrice@1s` |
| Historial de funding | `GET /fapi/v1/fundingRate` (límite 500 / 5 min / IP) | – |

- Peso: se lee `X-MBX-USED-WEIGHT-1M` y hay un tope propio de 600/min. Ante 429/418 el cliente se detiene y muestra `Retry-After`; no reintenta solo.
- WebSocket: rutas `/market` y `/public` (las URL antiguas sin ruta dejaron de funcionar en 2026), reconexión con espera creciente (1→30 s), renovación antes de las 24 h.
- Calidad (`src/futuros/quality`): datos viejos, huecos y duplicados en velas, OHLC incoherente, saltos y rangos anormales, libro vacío o cruzado, libro/mark/índice muy separados, reloj del PC desfasado, conexión caída o stream en silencio. Si algo falla → **NO APTO para operar**.
- Guardado: `data/mercado.sqlite` (ignorado por git). Comando: `futuros-datos`.

## Fase 3 – indicadores y estrategia (detalle)
- `features/indicadores.py`: EMA, ATR (Wilder), VWAP móvil y volumen promedio, todo en Decimal y solo sobre velas cerradas.
- `strategy/cruce_ema.py`: la señal **LONG** sale cuando la EMA 9 cruza hacia arriba a la EMA 21, el cierre está sobre el VWAP y el volumen es al menos 1,2× el promedio. **SHORT** es lo mismo hacia abajo.
  Filtros: datos APTOS, dirección permitida, ATR dentro de una banda, spread bajo y un objetivo que cubra 2× las comisiones de entrada y salida.
  Stop a 1,5 ATR y objetivo a 2 ATR. Intervalo de 5m, porque en 1m el movimiento típico casi no cubre las comisiones.
- Solo **propone**: no calcula tamaño ni apalancamiento y no envía nada. Eso es del motor de riesgo (Fase 4).
- Parámetros editables en `config/default.yaml` → `estrategia:`. La comisión es una referencia: verifica la de tu cuenta.
- Comando `futuros-senales`, que guarda las señales en `data/mercado.sqlite`, tabla `senales`.
- Sin garantía de rentabilidad: estas reglas se pondrán a prueba con el backtest (Fase 5) antes de cualquier uso.

## Fase 4 – motor de riesgo (detalle)
- `risk/motor.py`: `MotorRiesgo.evaluar(señal, reglas, cuenta)` → `Decision` (aprobada + `OrdenPropuesta`, o la lista de **todos** los rechazos). No envía nada.
- Revisa: 2x rígido (también si la config se salta la validación), modo real bloqueado, datos APTOS, símbolo/dirección, stop obligatorio y del lado correcto,
  pérdida diaria (bloquea al llegar al máximo y limita el riesgo a lo que queda del día), máximo de posiciones, sin promediar,
  tamaño por riesgo con comisiones incluidas, exposición total, reglas del exchange (`/fapi/v1/exchangeInfo`: tick, paso, mínimos),
  distancia a liquidación y ganancia neta ≥ objetivo neto.
- Sin martingala: la base del riesgo es el menor entre capital de referencia y capital actual; tras pérdidas el tamaño baja, tras ganancias no sube.
- `config/` ahora se instala como paquete, así los comandos de consola leen `config/limits.py` (antes solo funcionaba dentro de pytest).
- Comando `futuros-riesgo` (cuenta simulada). `--ejemplo` agrega señales hipotéticas y `--pnl-dia -15` simula una pérdida del día.
- Hallazgo: con 500 USDT, 2x y la volatilidad de octubre de 2026, un objetivo de 2 ATR en BTC deja ~0,46 USDT netos (las comisiones taker cuestan ~1 USDT por operación),
  menos que el objetivo de 1,50, y el motor rechaza. Se analizará con el backtest (Fase 5); los parámetros los decide el usuario.

## Fase 5 – backtest (detalle)
- `futuros-historico --dias 90`: descarga velas con `/fapi/v1/klines` y `startTime`, en bloques de 1000 (peso 5).
  Pausa si se acaba nuestro tope de peso, se detiene ante 429/418 y retoma donde quedó. También informa los huecos.
- `futuros-backtest`: la estrategia propone y el **motor de riesgo decide**, con el mismo código que en vivo. Luego se simula vela por vela.
  - Entrada en la apertura siguiente con deslizamiento en contra; comisión taker en la entrada y en la salida.
  - Si una vela toca el stop y el objetivo, se asume stop. Si el precio salta el stop, se sale en la apertura.
  - Las ventanas con huecos se tratan como NO APTAS.
  - Una sola posición a la vez; la pérdida diaria se reinicia a las 00:00 UTC.
- Informe en `reports/` (ignorado por git):
  - neto, comisiones, acierto, factor de beneficio, caída máxima, peor racha y motivos de rechazo;
  - el primer tramo (70 %) comparado con el tramo final (30 %), para detectar resultados que no se sostienen;
  - un aviso si hay menos de 30 operaciones.
- `--objetivo-neto` y `--comision` sirven para simulaciones "¿y si...?" y NO modifican `config/default.yaml`.
- Limitaciones: no se aplica el filtro de spread (no hay libro histórico) ni se cobra funding.
