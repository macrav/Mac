"""Fuente Nexo Inmobiliario (nexoinmobiliario.pe).

Es el portal de proyectos nuevos (preventa, en construccion y estreno). La
pagina de busqueda trae embebido, en una variable de JavaScript, el catalogo
completo de proyectos del pais con coordenadas y rango de precios, asi que
una sola descarga alcanza.

Ojo: un proyecto publica un rango (precio y dormitorios minimo/maximo), no una
unidad concreta. El precio que se usa aca es el minimo del proyecto, que es el
piso real de entrada; hay que confirmar con la constructora que ese precio
corresponda a un departamento de 1 o 2 dormitorios.
"""

import json
import re

from .. import http
from ..aviso import Aviso

NOMBRE = "Nexo Inmobiliario"
URL_BUSQUEDA = "https://nexoinmobiliario.pe/departamentos"
PATRON = re.compile(r"var\s+search_all_data\s*=\s*(\[.*?\]);", re.S)


def buscar(dormitorios=(1, 2), precio_max_usd=300_000, tipo_cambio=3.37,
           log=print, **_):
    html = http.get(URL_BUSQUEDA, timeout=120).decode("utf-8", "replace")
    m = PATRON.search(html)
    if not m:
        log(f"  {NOMBRE}: no se encontro el catalogo embebido")
        return []
    crudos = json.loads(m.group(1))
    log(f"  {NOMBRE}: {len(crudos)} proyectos en el catalogo nacional")

    avisos = []
    for x in crudos:
        a = _a_aviso(x)
        if a is None:
            continue
        # El proyecto sirve si su rango de dormitorios toca lo que buscamos.
        if not any(a.dormitorios_min <= d <= a.dormitorios_max for d in dormitorios):
            continue
        precio_usd = a.precio / tipo_cambio if a.moneda == "PEN" else a.precio
        if precio_usd > precio_max_usd:
            continue
        avisos.append(a)
    return avisos


def _a_aviso(x):
    try:
        lat = float(x.get("coord_lat") or 0)
        lon = float(x.get("long") or 0)
    except (TypeError, ValueError):
        return None
    if not lat or not lon:
        return None
    try:
        precio = float(x.get("min_price") or 0)
    except (TypeError, ValueError):
        precio = 0.0
    moneda = "PEN" if "S/" in (x.get("coin") or "") else "USD"
    return Aviso(
        fuente=NOMBRE,
        id=str(x.get("project_id") or ""),
        titulo=(x.get("name") or "").strip(),
        url=x.get("url") or "",
        lat=lat,
        lon=lon,
        distrito=x.get("distrito") or "",
        direccion=x.get("direccion") or "",
        dormitorios_min=int(float(x.get("room_min") or 0)),
        dormitorios_max=int(float(x.get("room_max") or 0)),
        banos=int(float(x.get("bathroom_min") or 0)),
        m2=float(x.get("area_min") or 0),
        precio=precio,
        moneda=moneda,
        estacionamiento=int(float(x.get("parking_min") or 0)),
        es_proyecto=True,
        constructora=x.get("builder_name") or "",
        contacto=x.get("project_contact") or "",
    )
