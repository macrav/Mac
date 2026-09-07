"""Modelo comun a todas las fuentes."""

from dataclasses import asdict, dataclass, field


@dataclass
class Aviso:
    fuente: str
    id: str
    titulo: str
    url: str
    lat: float
    lon: float
    distrito: str
    direccion: str = ""
    dormitorios_min: int = 0
    dormitorios_max: int = 0
    banos: int = 0
    m2: float = 0.0
    precio: float = 0.0          # tal como lo publica la fuente
    moneda: str = "USD"          # "USD" o "PEN"
    estacionamiento: int = 0
    piso: int = 0
    anio: str = ""
    es_proyecto: bool = False
    constructora: str = ""
    contacto: str = ""
    # Campos calculados por el pipeline.
    precio_pen: float = 0.0
    precio_usd: float = 0.0
    precio_m2_usd: float = 0.0
    km: float = 0.0
    cuota_10: float = 0.0        # cuota mensual con la inicial minima
    inicial_requerida: float = 0.0
    inicial_requerida_pct: float = 0.0
    alcanzable: bool = False
    geo_dudosa: bool = False
    precio_dudoso: bool = False
    alertas: list = field(default_factory=list)

    def dict(self):
        return asdict(self)
