# KINELO — base de datos, análisis y modelo

Sistema de análisis del juego KINELO de La Tinka. Sin dependencias externas:
solo Python 3.11 y su librería estándar.

```bash
python3 analyze.py       # informe completo
python3 analyze.py --tickets   # solo la cartera de 4 tickets
python3 test_kinelo.py   # pruebas (~2 min, incluye validación Monte Carlo)
```

## El resultado, en corto

Kinelo no se puede predecir, y no por falta de datos ni de método: los números
salen de un generador de números aleatorios certificado, no de una bolillera
física. No hay sesgo mecánico que descubrir, que es la única fuente de ventaja
que ha existido alguna vez en loterías reales.

Lo que sí se puede optimizar, y este sistema lo hace, son dos cosas medibles:

1. **El tipo de apuesta.** El retorno esperado va de 74.05% a 80.43% según
   cuántos números se marquen. Elegir bien vale 6.4 puntos porcentuales.
2. **El solapamiento entre tickets del mismo sorteo.** Con idéntico gasto y
   retorno esperado, usar números disjuntos baja la desviación estándar de
   38.84 a 19.36 y la probabilidad de no cobrar nada del 63% al 13%.

La ventaja de la casa es del 19.57% en la mejor variante y es estructural: está
escrita en la tabla de premios del reglamento. Ninguna elección de números la
mueve.

## Reglas (Reglamento oficial, artículos 1°, 19° y 26°)

| | |
|---|---|
| Sorteo | Un RNG escoge 20 números de 80, sin repetición |
| Frecuencia | Cada 5 minutos, de 06:00 a 02:00 (240 sorteos/día) |
| Jugada | El jugador marca de 1 a 10 números |
| Precio | S/ 1.00 la jugada simple |

## Retorno esperado por tipo de apuesta

Cálculo exacto con la hipergeométrica, `P(k) = C(20,k)·C(60,n-k)/C(80,n)`.

| Tipo | RTP | Ventaja casa | P(cobra algo) | 1ra categoría |
|-----:|------:|------:|------:|------:|
| 10 | 79.204% | 20.796% | 25.78% | 1 en 8,911,711 |
| 9 | 79.737% | 20.263% | 21.68% | 1 en 1,380,688 |
| 8 | 80.000% | 20.000% | 19.06% | 1 en 230,115 |
| 7 | 78.835% | 21.165% | 23.66% | 1 en 40,979 |
| 6 | 78.635% | 21.365% | 16.16% | 1 en 7,753 |
| **5** | **80.432%** | **19.568%** | **36.71%** | **1 en 1,551** |
| 4 | 79.648% | 20.352% | 25.89% | 1 en 326 |
| 3 | 76.315% | 23.685% | 15.26% | 1 en 72 |
| 2 | 74.051% | 25.949% | 43.99% | 1 en 17 |
| 1 | 75.000% | 25.000% | 25.00% | 1 en 4 |

El tipo 5 gana en las dos columnas que importan: mejor retorno y la segunda
mejor frecuencia de cobro.

Para dimensionar: una tragamonedas regulada devuelve 92-96%, la ruleta europea
97.3%.

## Estado de los datos

**No existe un histórico público de Kinelo descargable.** Lo verificado el
2026-08-23, con el detalle en `collector.py`:

- `m.latinka.com.pe` devuelve el mismo HTML para cualquier ruta, incluidas
  rutas inventadas (mismo md5). Es una shell que se arma en el cliente.
- El backend de resultados es `i.do?m=resultados&t=1&s=1121` (Kinelo es el
  juego 1121, según `layer-view-script/common/utils.js`). Responde 404 o cae
  en la shell sin sesión iniciada.
- `games.xml` publica Tinka, Kábala, Ganagol y Gana Diario. Kinelo no: son 240
  sorteos diarios y no entra en ese feed.
- `www.kinelo.com.pe`, que el Art. 21° señala como lugar de publicación, no
  resuelve desde fuera del Perú.

El sistema queda listo para cargar datos reales en cuanto se capturen desde una
sesión propia (`collector.ingest_manual`, `ingest_from_json`, `ingest_from_api`).
Mientras tanto trabaja con un corpus simulado, marcado como tal en la columna
`source` de la base para que no haya forma de confundirlo con datos reales.

## Qué contiene cada módulo

| Archivo | Qué hace |
|---|---|
| `paytable.py` | Tabla de premios oficial, transcrita del reglamento |
| `kinelo_math.py` | RTP, varianza y probabilidades exactas (Fraction, sin simular) |
| `stats_util.py` | chi-cuadrado, normal y corrección FDR, validados contra scipy |
| `db.py` | Esquema SQLite; sorteos como bitmask de 80 bits |
| `collector.py` | Carga de datos y estado del acceso a las fuentes |
| `simulate.py` | Sorteos sintéticos, limpios o con sesgo inyectado |
| `randomness.py` | Seis tests de aleatoriedad |
| `strategies.py` | Diez estrategias de predicción, con estado incremental |
| `backtest.py` | Backtest sin fuga de información, con intervalos de confianza |
| `portfolio.py` | Covarianza exacta entre tickets del mismo sorteo |
| `tickets.py` | Generador de carteras de mínima varianza |
| `analyze.py` | Informe completo |

## Sobre la validación

Dos cosas hacen que este análisis se sostenga, y las dos están en las pruebas:

**Los tests tienen potencia demostrada.** Un sesgo de apenas +15% en 5 números
se detecta con 5,000 sorteos (21 días de Kinelo) a p < 1e-6. Que no encuentren
nada en un histórico limpio es un resultado, no una limitación del método. Un
test que nunca detecta nada no sirve para nada.

**La matemática exacta cuadra con la simulación.** Cada fórmula cerrada
—retorno, varianza, covarianza entre tickets, probabilidad de no cobrar nada—
se contrasta contra Monte Carlo de cientos de miles de sorteos en
`test_kinelo.py`.

## Sobre el backtest

Todas las estrategias ven solo el pasado y se evalúan sobre los mismos sorteos.
El criterio para decir que una "funciona" es que su retorno supere el 100% con
significancia estadística, no que le gane a la estrategia al azar.

En una corrida típica la mejor estrategia marca ~89% de retorno contra el 80.4%
teórico, lo que parece una ventaja de nueve puntos. Su intervalo de confianza
al 95% es [79.1%, 99.9%]: contiene al teórico y no llega a 100%. Es ruido.

Así se fabrica un sistema "ganador": se prueban muchas variantes y se publica
la que quedó arriba, sin el intervalo de confianza al lado. Por eso el backtest
reporta siempre el intervalo.

## Nota

Este proyecto es de análisis matemático. Con una ventaja de la casa del 19.57%,
la jugada de mayor valor esperado es no jugar. Cualquier otra tiene valor
esperado negativo, y ninguna estrategia de selección de números cambia eso.

Si jugar deja de ser entretenimiento: Línea 113 (Minsa), opción 5, salud mental.

## Fuentes

- Reglamento oficial: https://www.latinka.com.pe/latinka/docs/reglamento/reglamento-kinelo.pdf
- Página del juego: https://m.latinka.com.pe/game_kinelo_show_home.html
- Tutorial: https://blog.latinka.com.pe/tutorial/como-jugar-kinelo/
