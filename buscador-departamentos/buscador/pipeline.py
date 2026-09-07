"""Orquesta la busqueda: descarga, limpia, mide distancias y evalua la cuota."""

from . import geo
from .config import (DISTRITOS_EN_RADIO, PRECIO_M2_MIN_USD, PRECIO_MAX_USD,
                     PRECIO_MIN_USD, Busqueda)
from .fuentes import FUENTES
from .hipoteca import cuota_mensual, inicial_requerida, precio_maximo


def descargar(fuentes, dormitorios, precio_max_usd, tipo_cambio, log=print):
    avisos = []
    for nombre in fuentes:
        modulo = FUENTES[nombre]
        log(f"Descargando de {modulo.NOMBRE}...")
        try:
            avisos += modulo.buscar(
                dormitorios=dormitorios,
                precio_max_usd=precio_max_usd,
                tipo_cambio=tipo_cambio,
                log=log,
            )
        except Exception as e:  # una fuente caida no debe tumbar la busqueda
            log(f"  ! {modulo.NOMBRE} fallo: {e}")
    return avisos


def _clave(a):
    return (
        a.fuente,
        round(a.lat, 5),
        round(a.lon, 5),
        round(a.precio),
        round(a.m2),
        a.dormitorios_min,
        geo.normaliza_texto(a.titulo)[:60],
    )


def deduplicar(avisos):
    vistos, salida = set(), []
    for a in avisos:
        k = _clave(a)
        if k in vistos:
            continue
        vistos.add(k)
        salida.append(a)
    return salida


def procesar(avisos, b: Busqueda, tipo_cambio: float):
    """Calcula distancia, precios, cuotas y alertas. Devuelve solo los del radio."""
    dentro = []
    for a in avisos:
        a.km = round(geo.distancia_km(b.lat, b.lon, a.lat, a.lon), 3)
        if a.km > b.radio_km:
            continue

        a.precio_usd = a.precio / tipo_cambio if a.moneda == "PEN" else a.precio
        a.precio_pen = a.precio if a.moneda == "PEN" else a.precio * tipo_cambio

        a.precio_m2_usd = round(a.precio_usd / a.m2, 2) if a.m2 else 0.0

        a.alertas = []
        a.precio_dudoso = not (PRECIO_MIN_USD <= a.precio_usd <= PRECIO_MAX_USD)
        if a.precio_m2_usd and a.precio_m2_usd < PRECIO_M2_MIN_USD:
            a.precio_dudoso = True
            a.alertas.append(
                f"US$ {a.precio_m2_usd:,.0f}/m2 es demasiado bajo para la zona: "
                "el precio o el area del aviso estan mal")
        if a.precio_usd < PRECIO_MIN_USD:
            a.alertas.append("precio demasiado bajo para una compra "
                             "(probable alquiler o dato incompleto)")
        elif a.precio_usd > PRECIO_MAX_USD:
            a.alertas.append("precio fuera del rango razonable")
        distrito = geo.normaliza_texto(a.distrito)
        a.geo_dudosa = bool(distrito) and distrito not in DISTRITOS_EN_RADIO
        if a.geo_dudosa:
            a.alertas.append(f"el distrito declarado ({a.distrito}) no llega a "
                             f"{b.radio_km:g} km del punto: coordenada dudosa")
        if a.es_proyecto:
            a.alertas.append("proyecto en venta: el precio es el minimo del "
                             "edificio, confirmar tipologia")

        c = b.credito
        inicial_min = a.precio_pen * c.inicial_pct_minima
        a.cuota_10 = round(cuota_mensual(a.precio_pen, inicial_min, c).total, 2)
        req = inicial_requerida(b.cuota_max, a.precio_pen, c)
        a.inicial_requerida = round(req, 2)
        a.inicial_requerida_pct = round(req / a.precio_pen, 4) if a.precio_pen else 0
        # Alcanzable = con la inicial que Mario tenga disponible, la cuota entra.
        a.alcanzable = bool(
            c.inicial_monto
            and c.inicial_monto >= req
            and not a.precio_dudoso
        )
        dentro.append(a)

    dentro.sort(key=lambda x: (x.inicial_requerida, x.precio_pen))
    return dentro


def filtrar(avisos, b: Busqueda, incluir_dudosos=False):
    salida = []
    for a in avisos:
        if not incluir_dudosos and (a.geo_dudosa or a.precio_dudoso):
            continue
        if not any(a.dormitorios_min <= d <= a.dormitorios_max
                   for d in b.dormitorios):
            continue
        salida.append(a)
    return salida


def resumen_capacidad(b: Busqueda, tipo_cambio: float) -> dict:
    """Cuanto se puede comprar con la cuota tope, segun la inicial disponible."""
    c = b.credito
    filas = []
    for inicial in (0, 20_000, 40_000, 60_000, 80_000, 100_000, 150_000, 200_000):
        precio = precio_maximo(b.cuota_max, inicial, c)
        filas.append({
            "inicial_pen": inicial,
            "precio_max_pen": round(precio, 2),
            "precio_max_usd": round(precio / tipo_cambio, 2),
            "prestamo_pen": round(max(precio - inicial - c.bono_buen_pagador, 0), 2),
        })
    return {
        "cuota_max": b.cuota_max,
        "tea": c.tea,
        "plazo_anios": c.plazo_anios,
        "inicial_pct_minima": c.inicial_pct_minima,
        "filas": filas,
    }
