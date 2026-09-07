"""Utilidades geograficas."""

import math
import unicodedata

RADIO_TIERRA_KM = 6371.0088


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en linea recta (haversine) entre dos coordenadas."""
    r = math.pi / 180
    dlat = (lat2 - lat1) * r
    dlon = (lon2 - lon1) * r
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(dlon / 2) ** 2
    )
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))


def caja(lat: float, lon: float, radio_km: float):
    """Bounding box (lat_min, lat_max, lon_min, lon_max) que contiene al circulo."""
    dlat = radio_km / 110.574
    dlon = radio_km / (111.320 * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def normaliza_texto(s: str) -> str:
    """Minusculas sin tildes, para comparar nombres de distrito."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())
