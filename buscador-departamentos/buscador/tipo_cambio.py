"""Tipo de cambio S/ por US$ desde el BCRP, con respaldo local."""

import datetime
import json

from . import http
from .config import TIPO_CAMBIO_FALLBACK

# Serie diaria "TC Sistema bancario SBS (S/ por US$) - Venta".
SERIE_BCRP = "PD04640PD"
URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{s}/json/{d}/{h}/ing"


def tipo_cambio(dias_atras: int = 20) -> tuple:
    """Devuelve (valor, fuente). Cae al valor de respaldo si el BCRP falla."""
    hoy = datetime.date.today()
    desde = hoy - datetime.timedelta(days=dias_atras)
    url = URL.format(s=SERIE_BCRP, d=desde.isoformat(), h=hoy.isoformat())
    try:
        datos = json.loads(http.get(url, timeout=40, intentos=2))
        valores = [
            float(p["values"][0])
            for p in datos.get("periods", [])
            if p["values"] and p["values"][0] not in ("n.d.", "")
        ]
        if valores:
            return valores[-1], f"BCRP serie {SERIE_BCRP}"
    except Exception:
        pass
    return TIPO_CAMBIO_FALLBACK, "valor de respaldo (BCRP no respondio)"
