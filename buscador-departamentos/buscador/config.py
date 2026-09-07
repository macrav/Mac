"""Parametros por defecto de la busqueda.

Todo lo que esta aca se puede sobreescribir desde la linea de comandos.
"""

from dataclasses import dataclass, field

# Av. Camino Real 1053, San Isidro (oficinas de Vinatea & Toyama).
# Coordenada interpolada entre los portales 1037 y 1075 de la Av. Camino Real
# segun los puntos con direccion de OpenStreetMap.
REFERENCIA_NOMBRE = "Av. Camino Real 1053, San Isidro"
REFERENCIA_LAT = -12.10470
REFERENCIA_LON = -77.03872

RADIO_KM = 2.0
DORMITORIOS = (1, 2)
CUOTA_MAX_PEN = 1500.0

# Distritos cuyo territorio realmente cae dentro de 2 km del punto de referencia.
# Sirve para descartar avisos mal geolocalizados: varios portales ponen el pin
# en el centro del distrito o en una coordenada por defecto.
DISTRITOS_EN_RADIO = {
    "san isidro",
    "orrantia",
    "lince",
    "miraflores",
    "surquillo",
    "jesus maria",
    "la victoria",
    "santa beatriz",
}

# Precio minimo creible en USD para una compra: por debajo de esto casi siempre
# es un alquiler mal publicado o un precio incompleto.
PRECIO_MIN_USD = 20_000.0
PRECIO_MAX_USD = 600_000.0

# Piso de precio por m2 (US$) en esta zona de Lima. Por debajo casi siempre es
# un error de carga: precio en soles publicado como dolares, area equivocada,
# o un aviso de alquiler.
PRECIO_M2_MIN_USD = 700.0

# Tipo de cambio de respaldo si el BCRP no responde (S/ por US$).
TIPO_CAMBIO_FALLBACK = 3.37


@dataclass
class SupuestosCredito:
    """Supuestos del credito hipotecario.

    Los seguros son mensuales y siguen la practica de la banca peruana:
    el desgravamen se cobra sobre el saldo del prestamo y el seguro del
    inmueble sobre el valor de la propiedad. Las tasas por defecto son
    ordenes de magnitud de mercado; conviene reemplazarlas por las que
    cotice cada banco.
    """

    tea: float = 0.105                 # tasa efectiva anual en soles
    plazo_anios: int = 20
    inicial_pct_minima: float = 0.10   # cuota inicial minima exigida
    inicial_monto: float = 0.0         # cuota inicial disponible, en soles
    desgravamen_mensual: float = 0.00050   # sobre el saldo del prestamo
    seguro_inmueble_mensual: float = 0.00030  # sobre el valor del inmueble
    portes: float = 0.0                # cargos fijos mensuales
    bono_buen_pagador: float = 0.0     # BBP del Fondo MIVIVIENDA, si aplica

    @property
    def meses(self) -> int:
        return self.plazo_anios * 12


@dataclass
class Busqueda:
    lat: float = REFERENCIA_LAT
    lon: float = REFERENCIA_LON
    radio_km: float = RADIO_KM
    dormitorios: tuple = DORMITORIOS
    cuota_max: float = CUOTA_MAX_PEN
    credito: SupuestosCredito = field(default_factory=SupuestosCredito)
    filtrar_distritos: bool = True
