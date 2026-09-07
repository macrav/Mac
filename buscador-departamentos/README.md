# Buscador de departamentos — 2 km alrededor de Av. Camino Real 1053, San Isidro

Busca departamentos **de 1 y 2 dormitorios en venta** dentro de un radio de 2 km
de la oficina de Vinatea & Toyama (Av. Camino Real 1053, San Isidro, Lima) y los
ordena por lo que realmente decide la compra cuando hay un tope de cuota mensual:
**cuánta cuota inicial hay que poner para que la cuota no pase de S/ 1,500**.

No necesita instalar nada: solo Python 3.9 o superior, librería estándar.

## Uso

```bash
python3 -m buscador --inicial 60000 --cuota-max 1500
```

Genera tres archivos en `datos/`:

| Archivo | Para qué sirve |
|---|---|
| `resultados.csv` | abrirlo en Excel y filtrar a mano |
| `resultados.json` | los mismos datos, para reprocesar |
| `buscador.html` | buscador interactivo: mapa, filtros y simulador de cuota |

`buscador.html` es autónomo: se abre con doble clic, funciona sin internet y
recalcula todo (cuotas, inicial requerida, mapa) al mover los controles.

### Opciones principales

```
--radio 2.0              radio en kilómetros
--dormitorios 1 2        cantidad exacta de dormitorios
--cuota-max 1500         cuota mensual máxima en soles
--inicial 60000          cuota inicial disponible en soles
--tea 10.5               tasa efectiva anual en %
--plazo 20               plazo en años
--inicial-minima 10      inicial mínima que exige el banco, en %
--bono 0                 Bono del Buen Pagador u otro subsidio, en soles
--lat / --lon            mover el punto de referencia
--fuentes infocasas nexo qué portales consultar
--incluir-dudosos        no descartar avisos con datos inconsistentes
```

## Qué encontró la primera corrida (07/09/2026)

- **735 departamentos** de 1 o 2 dormitorios en venta dentro de los 2 km,
  repartidos en Miraflores (364), San Isidro (263), Lince (62) y Surquillo (44).
- El precio mediano de la zona es de **US$ 2,650 por m²**.
- Con una cuota tope de **S/ 1,500 al mes** (TEA 10.5%, 20 años, seguros
  incluidos) el préstamo que se puede pagar es de **unos S/ 145,000**, es decir
  **US$ 43,000**. Ningún departamento de la zona cuesta eso.
- Por lo tanto la restricción real no es el precio de lista sino la inicial:
  el aviso más accesible del radio pide **S/ 44,000** de inicial (24% de un
  departamento de 2 dormitorios y 55 m² en Surquillo, US$ 55,275), y el
  siguiente ya pide **S/ 78,000**. La mayoría del radio necesita entre 50% y 80%
  de inicial para que la cuota entre en S/ 1,500.
- Estirar el plazo a 30 años sube el techo de precio alrededor de 15%; bajar la
  TEA de 10.5% a 8% lo sube otro 15% aproximadamente. Ninguna de las dos cosas
  cambia el orden de magnitud: la palanca fuerte es la inicial.

El HTML permite volver a correr ese razonamiento con otros números sin tocar el
código.

## Cómo se calcula la cuota

Cuota francesa sobre el préstamo, más los dos seguros que cobra la banca peruana:

```
cuota(mes) = amortización + desgravamen × saldo + seguro_inmueble × valor
```

Se reporta la cuota del **primer mes**, que es la más alta porque el desgravamen
se cobra sobre el saldo: si esa cuota entra en el presupuesto, todas las
siguientes también. De ahí se despeja la inicial requerida:

```
inicial_requerida = max(valor × inicial_mínima,
                        valor − (cuota_max − valor × seguro) / (factor + desgravamen) − bono)
```

Los valores por defecto (TEA 10.5%, desgravamen 0.050% mensual, seguro del
inmueble 0.030% mensual, inicial mínima 10%) son órdenes de magnitud de mercado
y están pensados para reemplazarse por la cotización real de cada banco.

## Fuentes de datos

| Fuente | Qué aporta | Cómo se consulta |
|---|---|---|
| InfoCasas Perú | avisos individuales de reventa y estreno, con coordenadas | API GraphQL público que usa su propia web (`searchListing`) |
| Nexo Inmobiliario | proyectos nuevos en preventa y construcción | catálogo nacional embebido en la página de búsqueda |
| BCRP | tipo de cambio S/ por US$ del día | serie estadística `PD04640PD` |

Urbania y Adondevivir quedaron fuera: ambos responden 403 detrás de Cloudflare a
cualquier cliente que no sea un navegador real.

## Limpieza de datos

Los portales traen ruido y el buscador lo descarta antes de mostrar nada:

- avisos cuyo **precio por m² es imposible** para la zona (menos de US$ 700/m²),
  que casi siempre son precios en soles publicados como dólares, áreas mal
  cargadas o alquileres subidos como venta;
- avisos cuyo **distrito declarado no puede caer dentro del radio** — varios
  portales ponen el pin en una coordenada por defecto, y así aparecían
  departamentos de San Miguel o Barranco a 1.5 km de San Isidro;
- duplicados exactos del mismo aviso republicado.

En la corrida del 07/09/2026 eso descartó 24 de los 759 avisos del radio.

## Qué falta verificar a mano

- En los proyectos nuevos el precio es el **mínimo del edificio**: puede
  corresponder a una tipología distinta de la que se busca.
- El **Bono del Buen Pagador** tiene topes de valor de vivienda y requisitos
  propios; hay que confirmarlo con el Fondo MIVIVIENDA antes de contarlo.
- La cuota no incluye mantenimiento del edificio, impuesto predial ni arbitrios.

## Estructura

```
buscador/
  config.py        punto de referencia, radio y supuestos de crédito
  geo.py           distancia haversine y normalización de nombres
  hipoteca.py      cuota, inicial requerida y precio máximo alcanzable
  http.py          cliente HTTP con reintentos (solo librería estándar)
  tipo_cambio.py   tipo de cambio del BCRP
  aviso.py         modelo común a todas las fuentes
  fuentes/
    infocasas.py   InfoCasas Perú
    nexo.py        Nexo Inmobiliario
  pipeline.py      descarga, deduplica, mide distancias y evalúa cuotas
  reporte.py       arma el HTML
  plantilla.html   el buscador interactivo
  cli.py           línea de comandos
datos/             resultados generados
```
