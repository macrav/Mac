# Tinka: base de datos histórica y modelo

Base de datos de sorteos de La Tinka (Perú), pruebas estadísticas sobre si el
sorteo tiene alguna estructura aprovechable, y un generador de tickets.

Respuesta corta a la pregunta que motivó el proyecto: no se puede predecir qué
bolillas van a salir. Las pruebas están abajo y son bastante contundentes. Lo
que sí se puede medir, y se midió, es qué números juega la gente, que cambia
cuánto cobras si ganas (aunque no cambia la probabilidad de ganar).

## Qué hay

| Archivo | Para qué sirve |
|---|---|
| `scraper.py` | Descarga los sorteos y arma `data/tinka.sqlite` |
| `ganadores.py` | Extrae la tabla de premios de cada sorteo |
| `analisis.py` | Pruebas de uniformidad, independencia y backtest |
| `popularidad.py` | Estima qué tan jugado está cada número |
| `generador.py` | Genera los tickets |
| `data/sorteos.csv` | El histórico en CSV, por si lo quieres en Excel |
| `data/reporte.txt` | Salida completa del análisis |

Para reproducirlo todo desde cero:

```bash
pip install numpy scipy
python3 scraper.py --desde 440 --hasta 1400
python3 ganadores.py
python3 analisis.py
python3 popularidad.py
python3 generador.py --tickets 4
```

## La base de datos

837 sorteos, del 466 (28 de enero de 2018) al 1326 (19 de agosto de 2026).
Cada fila trae número de sorteo, fecha, las 6 bolillas, la boliyapa, el número
del "Sí o Sí" y la cantidad de ganadores en cada categoría de premio.

Faltan 24 sorteos dentro de ese rango (un 2.8%) porque la fuente sencillamente
no los publica. Como los huecos no dependen de qué números salieron, no sesgan
las frecuencias, pero sí conviene saltarlos al comparar un sorteo con el
anterior, y el código lo hace.

Los datos vienen de tinkaresultados.com, que no es la web oficial. Antes de
jugar algo conviene contrastar con latinka.com.pe.

### El detalle que arruina casi todos los análisis que circulan

La Tinka fue ampliando el bombo. En los datos se ve el momento exacto de cada
cambio:

| Formato | Sorteos | Fechas | Cantidad |
|---|---|---|---|
| 6 de 45 | 466–856 | ene 2018 – feb 2022 | 367 |
| 6 de 46 | 857–1002 | feb 2022 – jul 2023 | 146 |
| 6 de 48 | 1003–1114 | jul 2023 – ago 2024 | 112 |
| 6 de 50 | 1115–1279 | ago 2024 – mar 2026 | 165 |
| 6 de 53 | 1280–1326 | mar 2026 – ago 2026 | 47 |

Cualquier tabla de "los números que más salen en la historia de la Tinka" que
sume las cinco épocas está mal construida: el 46 lleva cuatro años existiendo y
el 53 lleva cinco meses, así que el 53 va a aparecer siempre al final de la
lista por razones que no tienen nada que ver con el azar.

Peor todavía: del formato actual (6 de 53) sólo existen 47 sorteos. Son 282
bolillas repartidas entre 53 números, o sea unas 5 apariciones por número. Con
esa cantidad de datos, la diferencia entre "el número más caliente" y "el más
frío" es puro ruido.

## Las pruebas

Todo esto sale de `analisis.py` y está en `data/reporte.txt`.

**El bombo es justo.** Chi-cuadrado de uniformidad dentro de cada época por
separado. Los p-valores van de 0.20 a 0.98; ninguno se acerca a ser
significativo. Además, para cada época se simuló cuánto se separan el número
más frecuente y el menos frecuente por azar puro: la separación observada cae
siempre dentro del intervalo simulado. En la época de 6 de 45, con 367 sorteos,
el número más salido acumuló 64 apariciones y la simulación predice 64.0 de
media. Clavado.

**No hay memoria de un sorteo al siguiente.** Cuatro pruebas distintas:

- Bolillas repetidas respecto del sorteo anterior (823 pares): chi-cuadrado
  1.75, p = 0.63.
- Autocorrelación de la suma de las 6 bolillas, de lag 1 a lag 5: todas por
  debajo de 0.07 en valor absoluto, ninguna significativa.
- Distribución de sequías (cada cuánto vuelve a salir un número): coincide con
  la geométrica que predice la independencia, p = 0.52. Un número "atrasado" no
  tiene ninguna probabilidad extra de salir.
- Regresión logística sobre 17,381 observaciones de bolilla × sorteo: el
  coeficiente de "qué tan caliente venía" es −0.008 con error estándar 0.026.
  El intervalo de confianza descarta incluso efectos pequeños.

**Ninguna estrategia clásica funciona.** Backtest sobre 378 sorteos: se arma un
ticket con las 100 jugadas previas y se cuenta cuántos números acierta.

| Estrategia | Aciertos por sorteo | p contra azar |
|---|---|---|
| Números calientes | 0.807 | 0.57 |
| Números fríos | 0.855 | 0.09 |
| Números atrasados | 0.818 | 0.43 |
| Azar puro | 0.807 | 0.58 |
| 1-2-3-4-5-6 fijo | 0.725 | 0.14 |

El valor teórico es 0.784. Todas empatan, incluido jugar siempre 1-2-3-4-5-6.

## Lo que sí tiene señal

Aquí está la parte útil. La web publica cuántos ganadores hubo en cada
categoría de cada sorteo. Eso permite medir algo que no se ve directamente: qué
números marca la gente. La lógica es simple. Si un número está muy jugado, los
sorteos en los que sale tienen más ganadores de 3 y 4 aciertos que los sorteos
en los que no sale.

Con una regresión de Poisson sobre 829 sorteos (usando los ganadores de 2
aciertos + boliyapa como control del volumen vendido) sale esto:

- Cada bolilla del sorteo que cae entre 1 y 31 sube un 4.2% la cantidad de
  ganadores de 3 aciertos (p = 0.001). Es el efecto cumpleaños: la gente juega
  fechas de nacimiento.
- Cada par de números seguidos (32-33, por ejemplo) baja un 4.8% los ganadores
  (p < 0.0001). La gente evita los consecutivos porque le parecen poco
  aleatorios.
- Perseguir números calientes: nada. El coeficiente es +0.001 con p = 0.85. Los
  jugadores peruanos no hacen eso, o al menos no lo suficiente para notarse.

Sin modelo de por medio, comparando directamente las medianas: los sorteos con
5 o 6 números en el rango 1–31 tuvieron un 24% más de ganadores por unidad de
volumen que los sorteos con 0, 1 o 2 (Mann-Whitney, p < 0.0001).

### El efecto crece con la categoría

Esto es lo que permite extrapolar al pozo. Se repite el modelo cambiando la
variable dependiente:

| Categoría | Coeficiente por bolilla en 1–31 | Coeficiente por par consecutivo |
|---|---|---|
| 3 aciertos | +0.061 ± 0.006 | −0.048 ± 0.009 |
| 4 aciertos | +0.129 ± 0.008 | −0.120 ± 0.012 |
| 5 aciertos | +0.184 ± 0.018 | −0.255 ± 0.030 |

Tiene sentido: acertar 3 números de la combinación refleja sólo una parte de lo
que la gente marcó, y mientras más números hay que acertar, más pesa que la
combinación completa sea popular. Ajustando la recta y llevándola a 6 aciertos
salen +0.248 y −0.348. Esa extrapolación es la parte más débil de todo el
trabajo, y por eso el generador reporta también el resultado sin extrapolar.

### Lo que no se pudo medir

Intenté estimar la popularidad número por número, con 53 indicadores en el
modelo (`popularidad.py`). El resultado honesto es que no se puede:

- La prueba conjunta sobre los 53 coeficientes da p = 0.9997.
- El encogimiento empírico-Bayes deja la varianza real dentro de cada banda en
  cero. Toda la dispersión que se ve entre números individuales es error de
  estimación.
- Partiendo la historia en dos mitades, las estimaciones correlacionan +0.68,
  pero al quitar el efecto bajos/altos la correlación cae a +0.33 (p = 0.026) y
  dentro del rango 1–31 desaparece (p = 0.19).

Queda una sospecha de que algo hay, sin evidencia sólida. Así que el generador
usa sólo la distinción gruesa (1–31 contra 32–53) y trata a todos los números
de cada banda como equivalentes.

## Los tickets

`generador.py` no predice nada. Genera combinaciones que cumplan estas
condiciones y elige entre las mejores:

- Cero o un número entre 1 y 31 (contra el efecto cumpleaños).
- Uno o dos pares de números seguidos (la gente los evita; más de dos no tiene
  respaldo, sólo 11 sorteos de 837 los tuvieron).
- Que no sea una combinación que ya salió alguna vez (hay gente que las juega).
- Sin progresiones aritméticas, sin tres números terminados en la misma cifra,
  sin cuatro de la misma decena, sin todos pares ni todos impares.
- Poco solapamiento entre los cuatro tickets, para no repetir la misma apuesta
  cuatro veces.

Con la semilla por defecto salen estos:

```
35 - 37 - 38 - 44 - 45 - 49
32 - 33 - 34 - 40 - 43 - 48
36 - 41 - 42 - 47 - 50 - 51
39 - 42 - 45 - 46 - 52 - 53
```

Índice de reparto estimado: 0.20x extrapolando al pozo, 0.31x usando sólo lo
medido en la categoría de 5 aciertos. Léelo así: si el pozo cae en uno de estos
tickets, se esperaría repartirlo con bastante menos gente que con una jugada
típica. La probabilidad de que caiga es exactamente la misma que la de
cualquier otra combinación, 1 en 22,957,480.

## La aritmética que no cambia

Con el pozo en 24.5 millones y la tabla de premios del sorteo 1326:

| Categoría | Probabilidad | Premio |
|---|---|---|
| 6 aciertos | 1 en 22,957,480 | el pozo |
| 5 + boliyapa | 1 en 3,826,247 | S/ 100,000 |
| 5 aciertos | 1 en 83,179 | S/ 5,000 |
| 4 + boliyapa | 1 en 33,272 | S/ 500 |
| 4 aciertos | 1 en 1,479 | S/ 100 |
| 3 + boliyapa | 1 en 1,109 | S/ 50 |
| 3 aciertos | 1 en 76 | S/ 10 |
| 2 + boliyapa | 1 en 101 | S/ 5 |

El valor esperado de un ticket es S/ 1.46 y cuesta S/ 5.00. Se pierden S/ 3.54
por jugada en promedio, y el modelo de arriba no arregla eso: sólo redistribuye
lo poco que se cobra en el caso improbable de ganar. Jugando dos veces por
semana durante 50 años, la probabilidad de acertar los 6 alguna vez es de 1 en
4,415.

## Advertencia

Esto es un ejercicio de estadística. La conclusión del análisis es que la Tinka
no se puede predecir, y los cuatro tickets de arriba no son una recomendación
de gasto. Si juegas, que sea con plata que puedas perder sin que te cambie el
mes.
