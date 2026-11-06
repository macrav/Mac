# TechMaC

Laboratorio local para probar estrategias de trading en serio, más un libro de órdenes en papel con
límites de riesgo y auditoría. Incluye un conector MCP para usarlo desde Claude.

- **100 % local.** Python 3.9+ y nada que instalar. Tus datos, evaluaciones y órdenes viven en
  `~/.techmac` (permisos 700/600).
- **Sin broker.** TechMaC no se conecta a Alpaca ni a nadie. Una orden aprobada es un ticket que tú
  ejecutas a mano en tu broker, si quieres.
- **Inspirado en** [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT). Puede
  importar su `trader/orders.json`.

> **No es asesoría financiera.** Un backtest aprobado no garantiza ganancias futuras. La mayoría de
> quienes hacen day trading pierden dinero.

## Qué lo hace "serio"

| Problema típico de un backtest | Cómo lo maneja TechMaC |
| --- | --- |
| Ver el futuro (lookahead) | La señal se calcula al cierre de la vela *i* y se ejecuta en la **apertura de *i+1***. Un test altera el futuro y comprueba que las señales pasadas no cambian. |
| Ignorar costos | Comisión por acción con mínimo, slippage y medio spread en cada lado. Además se repite todo con **costos x2**. |
| Fills optimistas | Gap bajo el stop: se sale a la apertura (peor precio). Stop y objetivo en la misma vela: cuenta el **stop**. El objetivo solo se llena si el precio lo **supera**. Gap bajo el stop antes de entrar: la entrada se cancela. |
| Sobreajuste (elegir los mejores parámetros a posteriori) | **Walk-forward**: optimiza en una ventana, opera la siguiente que nunca vio y avanza. Solo cuenta lo que pasó fuera de muestra. |
| Probar muchas combinaciones hasta que una salga bien | **Deflated Sharpe Ratio** (Bailey y López de Prado): descuenta el número de combinaciones probadas. |
| Pocas operaciones, mucha suerte | Intervalo de confianza bootstrap de la expectativa en R y un mínimo de operaciones fuera de muestra. |
| Rachas malas | **Monte Carlo por bloques**: remuestrea la secuencia de resultados conservando rachas y mide el drawdown p95. |
| "Gana", pero menos que el índice | Se compara con **comprar y mantener** en el mismo período. |
| Datos rotos | Cada vela se valida (precios positivos, máximo ≥ apertura/cierre ≥ mínimo, etc.), se guarda el hash de cada importación y se reportan sesiones incompletas. |

### El veredicto

`evaluate` devuelve **APROBADA para prueba en papel** solo si cumple todo esto (los umbrales se
cambian en `config.json` → `criteria`):

1. ≥ 100 operaciones fuera de muestra.
2. El extremo bajo del IC 95 % de la expectativa en R es > 0.
3. Profit factor neto de costos ≥ 1.2.
4. Deflated Sharpe ≥ 0.95.
5. La expectativa sigue siendo positiva con costos x2.
6. Drawdown p95 del Monte Carlo ≤ 20 %.
7. Sharpe mayor que comprar y mantener.

Si no, queda **RECHAZADA**. Una evaluación APROBADA es requisito para proponer órdenes.

### Resultados reales (datos de Yahoo hasta el 5 de noviembre de 2026, configuración por defecto)

| Prueba | Fuera de muestra | Veredicto |
| --- | --- | --- |
| SPY 1d, cruce de medias | 40 operaciones, +0.30 R, IC95 [-0.05, 0.69], Sharpe 0.29 vs 0.62 del índice | RECHAZADA |
| SPY 1d, Donchian | 109 operaciones, +0.23 R, IC95 [-0.02, 0.49], DSR 0.23 | RECHAZADA |
| QQQ 1d, Donchian | 85 operaciones, +0.39 R, IC95 [0.04, 0.77], DSR 0.66, Sharpe 0.41 vs 0.69 | RECHAZADA |
| AAPL 1d, cruce de medias | 66 operaciones, +0.17 R, con costos x2 −0.16 R | RECHAZADA |
| SPY 5m, ruptura de apertura (60 días) | 14 operaciones, −0.27 R | RECHAZADA |

Portafolios globales (`SPY EFA EEM GLD IEF SHY`, fuera de muestra de diciembre de 2010 a noviembre de 2026):

| Portafolio | CAGR | Sharpe | Máx. caída | Veredicto |
| --- | --- | --- | --- | --- |
| Comprar y mantener SPY (referencia) | 13.9 % | 0.85 | 33.7 % | — |
| Momentum dual | 6.7 % | 0.51 | 31.9 % | RECHAZADA |
| Momentum relativo | 7.7 % | 0.70 | 28.1 % | RECHAZADA |
| Paridad de riesgo | 5.8 % | 0.72 | 20.6 % | RECHAZADA |
| Tendencia + paridad de riesgo | 3.7 % | 0.64 | **13.8 %** | RECHAZADA |

Ranking de 7 estrategias × 4 activos (SPY, QQQ, EFA, GLD; 192 combinaciones): **las 24 RECHAZADAS**.
Las de tendencia (`trend_filter`, `tsmom`) quedaron arriba, pero ninguna superó el Sharpe de comprar y
mantener.

¿Cuánto tarda $10,000 en llegar a $1,000,000 con SPY (historia 1993–2026, 4,000 simulaciones)?

| Aporte | Apalancamiento | Años (mediana) | Llegar en ≤ 20 años | Caer 50 % en algún momento |
| --- | --- | --- | --- | --- |
| $0 | 1x | más de 40 | 0 % | 29 % |
| $0 | 3x | 24 | 20 % | 100 % |
| $500/mes | 1x | 25 | 9 % | 19 % |
| $500/mes | 2x | 20 | 46 % | 94 % |

Es lo que cabe esperar: las estrategias de manual, sin ventaja propia, no superan al índice. Los tests
incluyen además una serie sintética con tendencias reales donde el sistema **sí** aprueba, para
comprobar que el filtro no rechaza todo por diseño.

## Estrategias incluidas

Solo estrategias con respaldo publicado y ampliamente usadas en la industria. Ninguna es secreta ni
"garantizada": TechMaC las somete a todas al mismo examen.

**De un activo** (`evaluate`, `ranking`):

| Nombre | Origen | Idea |
| --- | --- | --- |
| `tsmom` | Moskowitz, Ooi y Pedersen (2012), base de los fondos CTA | Invertido mientras el retorno de N días es positivo |
| `trend_filter` | Meb Faber (2007) | Invertido sobre la media de 200 días; busca recortar las grandes caídas |
| `donchian` | Tortugas de Richard Dennis | Ruptura de máximos de N días |
| `sma_cross` | Clásico | Cruce de medias |
| `rsi2` | Larry Connors | Comprar retrocesos extremos dentro de una tendencia alcista |
| `ibs` | Literatura de reversión en índices | Comprar días que cierran cerca de su mínimo |
| `orb` | day-trader-skill | Ruptura del rango de apertura (intradía) |

**Portafolios globales con rebalanceo mensual** (`portfolio`), por ejemplo con
`SPY EFA EEM GLD IEF SHY` (EE. UU., desarrollados, emergentes, oro, bonos y bonos cortos):

| Nombre | Origen | Idea |
| --- | --- | --- |
| `dual_momentum` | Gary Antonacci (GEM) | Todo en el mejor activo de riesgo si su momentum es positivo; si no, al activo seguro |
| `relative_momentum` | Jegadeesh y Titman; Faber | Los mejores N activos por momentum, con filtro absoluto |
| `trend_parity` | GTAA de Faber + paridad de riesgo | Pesos por inversa de volatilidad; lo que esté bajo su media va al activo seguro |
| `risk_parity` | Bridgewater All Weather (idea) | Cada activo aporta un riesgo parecido |
| `equal_weight` | Referencia | Mismo peso en todo |

Opciones: `--target-vol` (apunta a una volatilidad anual) y `--max-leverage` (apagado por defecto; si
se usa, se cobra financiación). El veredicto de un portafolio exige ≥ 8 años fuera de muestra,
DSR ≥ 0.95, Sharpe mayor que el benchmark (también con costos x2) y una caída máxima ≤ 35 %. También
muestra **los pesos que tocaría tener hoy**.

**Ranking** (`ranking SPY QQQ EFA GLD`): evalúa todas las estrategias diarias en todos los símbolos.
El DSR de cada fila cuenta **todas** las combinaciones del ranking, porque quedarse con la mejor de
muchas también es sobreajuste.

**Simulador de meta** (`goal`): ¿cuánto tardo en llegar a $1,000,000 y qué probabilidad tengo de
quebrar? Remuestrea por bloques de 12 meses los retornos mensuales reales de una evaluación (fuera de
muestra) o de comprar y mantener un activo, con tu capital, tus aportes y varios niveles de
apalancamiento.

## Seguridad del conector TechMaC

- **Solo stdio.** No abre puertos ni escucha conexiones.
- **Red bloqueada.** Al arrancar, el servidor MCP deshabilita `socket` en su propio proceso. El único
  módulo con red (`fetch`) solo se usa desde la CLI, con HTTPS, una lista blanca de hosts (también en
  redirecciones), tamaño máximo y tiempo límite.
- **Claude solo propone.** No existe ninguna herramienta para aprobar, ejecutar, descargar ni desactivar
  el KILL. Aprobar exige una **terminal interactiva** (TTY) y escribir la frase exacta, por ejemplo
  `APROBAR 7 SPY 5`. Al aprobar se vuelven a revisar todos los límites.
- **Límites de riesgo** en cada propuesta y aprobación: pérdida máxima por operación, pérdida diaria
  (realizada + riesgo abierto + la nueva), operaciones por día, posiciones abiertas, beneficio/riesgo
  mínimo, tamaño máximo, lista de símbolos permitidos, evaluación APROBADA del mismo símbolo y no más
  vieja de 90 días, y vencimiento de propuestas (30 min).
- **Interruptor KILL.** `tm.py kill on` bloquea todo. Apagarlo exige una TTY.
- **Auditoría** de solo agregar (triggers de SQLite) y encadenada por SHA-256. `tm.py audit` detecta
  cualquier alteración. Anota el `head` de vez en cuando: si alguien con acceso a tu disco reescribe
  toda la cadena, solo ese ancla externa lo delata.
- **Validación estricta** de cada argumento: símbolos con regex, números finitos con límites,
  parámetros y argumentos desconocidos rechazados, rejilla de máximo 200 combinaciones y config.json
  con esquema.
- **Sin** `eval`, `pickle`, `subprocess` ni dependencias externas.

## Uso

```bash
python3 techmac/tm.py init                                  # crea ~/.techmac y config.json; ajusta tus límites
python3 techmac/tm.py fetch SPY QQQ --interval 1d           # historial diario completo (Yahoo, ajustado)
python3 techmac/tm.py fetch SPY --interval 5m               # últimos 60 días; córrelo a diario y el historial se acumula
python3 techmac/tm.py import-csv mis_datos.csv --symbol SPY --interval 5m   # tus propios datos (mejor calidad)
python3 techmac/tm.py data                                  # qué datos tienes y huecos
python3 techmac/tm.py strategies                            # orb, sma_cross, donchian y sus parámetros

python3 techmac/tm.py backtest SPY --strategy donchian --params '{"entry_n": 55}'    # exploración (en muestra)
python3 techmac/tm.py evaluate SPY --strategy donchian                               # veredicto serio
python3 techmac/tm.py evaluate SPY --interval 5m --strategy orb --train-days 40 --test-days 10
python3 techmac/tm.py evaluate QQQ --strategy sma_cross --grid '{"fast": [10, 20], "slow": [100, 200]}'

python3 techmac/tm.py ranking SPY QQQ EFA GLD                                       # todas contra todas
python3 techmac/tm.py fetch EFA EEM GLD IEF SHY
python3 techmac/tm.py portfolio SPY EFA EEM GLD IEF SHY --strategy trend_parity --safe SHY
python3 techmac/tm.py goal --symbol SPY --capital 10000 --monthly 500               # ¿cuándo llego al millón?
python3 techmac/tm.py goal --evaluation 14 --capital 10000 --monthly 500 --leverage 1,2

python3 techmac/tm.py propose SPY --qty 5 --entry 500 --stop 495 --target 510 --evaluation 12
python3 techmac/tm.py approve 1                             # solo en tu terminal, con la frase exacta
python3 techmac/tm.py record-fill 1 --price 500.10          # lo que te dio tu broker
python3 techmac/tm.py record-exit 1 --price 509.80
python3 techmac/tm.py ledger                                # P&L y expectativa real vs backtest
python3 techmac/tm.py audit --tail 10
python3 techmac/tm.py kill on
```

`--json` antes del comando devuelve JSON. `TECHMAC_HOME=/otra/ruta` usa otra carpeta de datos.

### En Claude Code

El archivo `.mcp.json` de la raíz del repo registra el conector `techmac`. Al abrir el repo, Claude
Code te pedirá permiso para activarlo. La skill `.claude/skills/techmac/SKILL.md` le explica a Claude
el flujo y sus reglas. Pídele cosas como "evalúa Donchian en QQQ y dime si pasa".

### En Claude Desktop

En `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "techmac": { "command": "python3", "args": ["-I", "/ruta/absoluta/a/Mac/techmac/tm_mcp.py"] }
  }
}
```

## Del backtest al dinero real: el camino recomendado

1. `evaluate` con datos suficientes: años de velas diarias o meses de intradía acumulados. 60 días de
   velas de 5 minutos casi nunca bastan.
2. Si queda APROBADA, opérala **en papel** varias semanas con `propose` → `approve` → `record-fill/exit`.
3. Compara la expectativa real de `ledger` con la del backtest. Si es mucho peor, el backtest estaba
   sobreajustado o los costos reales son mayores.
4. Solo entonces, y con un tamaño pequeño, considera dinero real, ejecutando tú cada orden en tu broker.

## Limitaciones honestas

- Los datos gratuitos de Yahoo no son oficiales. Tienen **sesgo de supervivencia** (no incluyen
  empresas que quebraron o salieron de bolsa) y solo dan 60 días de velas de 5 minutos. Para trabajo
  serio en intradía, importa datos de un proveedor con `import-csv`.
- Por ahora solo compras (sin cortos, opciones ni margen) y una posición por símbolo y evaluación.
- Los ETFs empiezan entre 1993 y 2005; el período fuera de muestra de los portafolios (2010–2026) fue
  excepcional para las acciones de EE. UU., lo que favorece a comprar y mantener SPY. En otras décadas
  (2000–2009) la diversificación y la tendencia lucieron mucho mejor. Prueba también con `--benchmark`
  distinto o con más historia importada.
- En portafolios, el efectivo no rinde nada (conservador) y el simulador de meta usa retornos mensuales,
  así que subestima las caídas dentro del mes.
- El motor trabaja con velas, no con ticks. Dentro de una vela asume el peor caso, que es conservador
  pero no exacto.
- La comparación del drawdown en % es aproximada: drawdown en R × riesgo por operación.

## Tests

```bash
cd techmac && python3 -m unittest -v
```

Corren sin internet: tiempo de Nueva York y cambio de horario, validación, permisos, integridad de
datos, reglas de ejecución (gaps, stop y objetivo en la misma vela, costos, sin margen, nunca de un día
para otro), ausencia de lookahead, DSR, walk-forward (rechaza un paseo aleatorio y aprueba una ventaja
real), límites de riesgo, frase de aprobación, KILL, auditoría a prueba de manipulación y el conector
MCP de punta a punta (sin herramienta de aprobación, red bloqueada, argumentos maliciosos rechazados).
