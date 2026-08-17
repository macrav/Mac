# Radar de ofertas (Perú)

Recolecta las ofertas vigentes de tiendas peruanas y las publica como una página
consultable con enlace y precio, marcando las que tienen pocas unidades disponibles.

Artifact: https://claude.ai/code/artifact/e7516adb-202e-4063-ab16-6cf23272ef00

## Uso

```bash
python3 run.py                      # todas las tiendas -> ofertas.html + data.json
python3 run.py --only falabella     # una sola tienda
python3 run.py --out /ruta/pag.html
```

Sólo usa la librería estándar y `curl`. Una corrida completa tarda ~4 minutos.

## Tiendas

| Tienda | Qué se obtiene | Cómo |
|---|---|---|
| **Falabella** | Ofertas, stock bajo, sexo, tallas, marca | **Next.js**: la colección `/collection/ofertas` viene como JSON dentro de `__NEXT_DATA__`. Se abre además la ficha de cada producto para leer `fomo`, la especificación *Género* y las tallas. |
| **Tai Loy** | Sólo ofertas y marca | **Magento 2** con grillas renderizadas en el servidor. Se recorren todas las categorías y se conserva lo que lleva precio regular tachado. |

La página muestra la plataforma de cada tienda en tarjetas bajo el resumen, con lo que
aporta cada una y cuántas ofertas trajo en la corrida.

### Sexo y tallas

Ninguno de los dos viaja en el listado de Falabella:

- **Sexo** — especificación `1349_genero_de_vestuario` (nombre `Género`) de la ficha. El
  recolector la busca por nombre y por el fragmento `genero` en el id, porque calzado y
  vestuario usan ids distintos. Valores típicos: Mujer, Unisex adulto, Niña, Unisex niño.
- **Tallas** — `variants[].options[].sizes[]`, campo `value` (no `label`). Se prefieren las
  que siguen comprables (`available: true`) y sólo se cae a todas si ninguna lo está.

Tai Loy no expone ninguno de los dos: su ficha sólo tiene categoría, código y marca.

### Sobre el aviso "Pocas unidades disponibles"

Falabella no dibuja ese aviso en su web de escritorio: el sitio trae el interruptor
`isFomoBadgeVisible` apagado y el texto no existe en su JavaScript. El dato sí viaja en
la ficha del producto, por variante:

```json
"fomo": {"enabled": true, "remainingUnits": 1}
```

Se lee la variante que la propia oferta muestra (`skuId`), con la variante por defecto
del producto como respaldo. El contador sólo devuelve **1 o 4**, así que es una señal de
urgencia y no un inventario exacto.

Tai Loy no publica ninguna señal de stock, en el listado ni en la ficha.

## Tiendas descartadas

| Tienda | Motivo |
|---|---|
| `simple.ripley.com.pe` | Cloudflare responde el interstitial "Just a moment..." (`cf-mitigated: challenge`) a todas las rutas, incluido `robots.txt` y el sitemap. |
| `www.adidas.pe` | Akamai devuelve 403 en todas las rutas de listado y en la API `content-engine`. |

Ambos exigen resolver un desafío de navegador. Un navegador real no es alternativa aquí:
el entorno sólo permite salida por un proxy que relaya `CONNECT` y resuelve el DNS, y
Chromium no atraviesa esa configuración. Si en algún momento hace falta cubrirlos, la vía
es un servicio externo de scraping con resolución de desafíos, o el feed oficial de cada
retailer.

## Estructura

- `common.py` — descarga con reintentos y ejecución concurrente.
- `falabella.py`, `tailoy.py` — un `scrape(log)` por tienda; devuelven filas con la misma forma.
- `render.py` — arma la página HTML autocontenida (filtros, búsqueda, orden).
- `run.py` — orquesta, tolera que una tienda falle y escribe el resumen en stdout.

Para agregar una tienda: crear un módulo con `scrape(log=print)` que devuelva filas con
`store, name, url, price, before, discount, amount, low_stock, units` y registrarlo en
`STORES` dentro de `run.py`.
