"""Genera el buscador en HTML: un archivo autonomo con los datos embebidos.

`cuerpo()` devuelve solo el contenido (sin <html>/<head>/<body>), que es lo
que espera el publicador de Artifacts. `escribir()` lo envuelve en un
documento completo para abrirlo en el navegador desde el disco.
"""

import json
import os

CAMPOS = [
    "km", "lat", "lon", "distrito", "dormitorios_min", "dormitorios_max",
    "m2", "precio_usd", "precio_pen", "precio_m2_usd", "es_proyecto",
    "titulo", "url", "fuente", "banos", "estacionamiento", "piso", "anio",
    "direccion", "constructora",
]


def _compactar(payload):
    filas = []
    for a in payload["avisos"]:
        filas.append([a.get(c) for c in CAMPOS])
    return {
        "campos": CAMPOS,
        "filas": filas,
        "referencia": payload["referencia"],
        "tipo_cambio": payload["tipo_cambio"],
        "tipo_cambio_fuente": payload["tipo_cambio_fuente"],
        "credito": payload["credito"],
        "generado": payload["generado"],
        "descartados": payload["descartados"],
    }


def cuerpo(payload) -> str:
    datos = json.dumps(_compactar(payload), ensure_ascii=False, separators=(",", ":"))
    plantilla = os.path.join(os.path.dirname(__file__), "plantilla.html")
    with open(plantilla, encoding="utf-8") as fh:
        html = fh.read()
    return html.replace("/*__DATOS__*/null", datos)


def escribir(payload, ruta):
    doc = (
        "<!doctype html>\n<html lang=\"es\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<style>:root{color-scheme:light dark}body{margin:0}"
        "img{max-width:100%}[hidden]{display:none!important}</style>\n"
        "</head>\n<body>\n" + cuerpo(payload) + "\n</body>\n</html>\n"
    )
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return ruta
