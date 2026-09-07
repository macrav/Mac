"""Linea de comandos del buscador."""

import argparse
import csv
import datetime
import json
import os
import sys

from . import pipeline, reporte
from .config import (CUOTA_MAX_PEN, DORMITORIOS, RADIO_KM, REFERENCIA_LAT,
                     REFERENCIA_LON, REFERENCIA_NOMBRE, Busqueda,
                     SupuestosCredito)
from .tipo_cambio import tipo_cambio as tc_bcrp


def parsear(argv=None):
    p = argparse.ArgumentParser(
        prog="buscador",
        description="Busca departamentos en venta cerca de un punto, con la "
                    "cuota mensual como filtro principal.",
    )
    g = p.add_argument_group("busqueda")
    g.add_argument("--lat", type=float, default=REFERENCIA_LAT)
    g.add_argument("--lon", type=float, default=REFERENCIA_LON)
    g.add_argument("--referencia", default=REFERENCIA_NOMBRE)
    g.add_argument("--radio", type=float, default=RADIO_KM,
                   help="radio en kilometros (por defecto %(default)s)")
    g.add_argument("--dormitorios", type=int, nargs="+", default=list(DORMITORIOS))
    g.add_argument("--fuentes", nargs="+", default=["infocasas", "nexo"],
                   choices=["infocasas", "nexo"])
    g.add_argument("--precio-max-usd", type=float, default=300_000,
                   help="tope de precio al consultar las fuentes")
    g.add_argument("--incluir-dudosos", action="store_true",
                   help="no descartar avisos con coordenada o precio sospechoso")

    f = p.add_argument_group("credito")
    f.add_argument("--cuota-max", type=float, default=CUOTA_MAX_PEN,
                   help="cuota mensual maxima en soles (por defecto %(default)s)")
    f.add_argument("--inicial", type=float, default=0.0,
                   help="cuota inicial disponible en soles")
    f.add_argument("--tea", type=float, default=10.5,
                   help="tasa efectiva anual en %% (por defecto %(default)s)")
    f.add_argument("--plazo", type=int, default=20, help="plazo en anios")
    f.add_argument("--inicial-minima", type=float, default=10.0,
                   help="inicial minima exigida por el banco, en %%")
    f.add_argument("--desgravamen", type=float, default=0.050,
                   help="seguro de desgravamen mensual en %% del saldo")
    f.add_argument("--seguro-inmueble", type=float, default=0.030,
                   help="seguro del inmueble mensual en %% del valor")
    f.add_argument("--bono", type=float, default=0.0,
                   help="Bono del Buen Pagador u otro subsidio, en soles")
    f.add_argument("--tc", type=float, default=None,
                   help="tipo de cambio S/ por US$ (por defecto, el del BCRP)")

    s = p.add_argument_group("salida")
    s.add_argument("--salida", default="datos", help="carpeta de resultados")
    s.add_argument("--sin-html", action="store_true")
    return p.parse_args(argv)


def construir_busqueda(a) -> Busqueda:
    credito = SupuestosCredito(
        tea=a.tea / 100.0,
        plazo_anios=a.plazo,
        inicial_pct_minima=a.inicial_minima / 100.0,
        inicial_monto=a.inicial,
        desgravamen_mensual=a.desgravamen / 100.0,
        seguro_inmueble_mensual=a.seguro_inmueble / 100.0,
        bono_buen_pagador=a.bono,
    )
    return Busqueda(
        lat=a.lat, lon=a.lon, radio_km=a.radio,
        dormitorios=tuple(a.dormitorios), cuota_max=a.cuota_max, credito=credito,
    )


CAMPOS_CSV = [
    "km", "distrito", "dormitorios_min", "dormitorios_max", "m2", "precio",
    "moneda", "precio_usd", "precio_pen", "precio_m2_usd", "cuota_10", "inicial_requerida",
    "inicial_requerida_pct", "alcanzable", "es_proyecto", "geo_dudosa",
    "precio_dudoso", "titulo",
    "direccion", "fuente", "url", "alertas",
]


def main(argv=None):
    a = parsear(argv)
    b = construir_busqueda(a)

    if a.tc:
        tc, fuente_tc = a.tc, "indicado en la linea de comandos"
    else:
        tc, fuente_tc = tc_bcrp()
    print(f"Tipo de cambio: S/ {tc:.3f} por US$ ({fuente_tc})")
    print(f"Referencia: {a.referencia}  ({a.lat}, {a.lon})  radio {a.radio} km")
    print(f"Cuota tope: S/ {a.cuota_max:,.0f}/mes  |  TEA {a.tea}%  |  "
          f"{a.plazo} anios  |  inicial disponible S/ {a.inicial:,.0f}")

    crudos = pipeline.descargar(a.fuentes, tuple(a.dormitorios),
                                a.precio_max_usd, tc)
    print(f"Avisos descargados: {len(crudos)}")
    crudos = pipeline.deduplicar(crudos)
    print(f"Tras quitar duplicados: {len(crudos)}")

    dentro = pipeline.procesar(crudos, b, tc)
    print(f"Dentro de {a.radio} km: {len(dentro)}")
    limpios = pipeline.filtrar(dentro, b, incluir_dudosos=a.incluir_dudosos)
    print(f"Con datos consistentes: {len(limpios)}")

    if a.inicial:
        alcanzables = [x for x in limpios if x.alcanzable]
        print(f"Con cuota <= S/ {a.cuota_max:,.0f} usando su inicial: "
              f"{len(alcanzables)}")

    os.makedirs(a.salida, exist_ok=True)
    payload = {
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "referencia": {"nombre": a.referencia, "lat": a.lat, "lon": a.lon,
                       "radio_km": a.radio},
        "tipo_cambio": tc,
        "tipo_cambio_fuente": fuente_tc,
        "credito": {
            "cuota_max": a.cuota_max, "tea": a.tea, "plazo_anios": a.plazo,
            "inicial_pct_minima": a.inicial_minima, "inicial": a.inicial,
            "desgravamen": a.desgravamen, "seguro_inmueble": a.seguro_inmueble,
            "bono": a.bono,
        },
        "capacidad": pipeline.resumen_capacidad(b, tc),
        "dormitorios": list(a.dormitorios),
        "avisos": [x.dict() for x in limpios],
        "descartados": len(dentro) - len(limpios),
    }
    ruta_json = os.path.join(a.salida, "resultados.json")
    with open(ruta_json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    ruta_csv = os.path.join(a.salida, "resultados.csv")
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_CSV, extrasaction="ignore")
        w.writeheader()
        for x in limpios:
            fila = x.dict()
            fila["alertas"] = " | ".join(fila["alertas"])
            w.writerow(fila)

    print(f"Escrito: {ruta_json}")
    print(f"Escrito: {ruta_csv}")
    if not a.sin_html:
        ruta_html = os.path.join(a.salida, "buscador.html")
        reporte.escribir(payload, ruta_html)
        print(f"Escrito: {ruta_html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
