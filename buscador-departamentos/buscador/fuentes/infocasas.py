"""Fuente InfoCasas Peru (www.infocasas.com.pe).

Usa el mismo API GraphQL que consume la web del portal. Se pide `searchListing`
porque devuelve latitud y longitud de cada aviso, que es lo que necesitamos
para medir la distancia al punto de referencia.
"""

from .. import http
from ..aviso import Aviso

NOMBRE = "InfoCasas"
ENDPOINT = "https://graph.infocasas.com.uy/graphql"
CABECERAS = {"X-Origin": "www.infocasas.com.pe"}
BASE_WEB = "https://www.infocasas.com.pe/"

OPERACION_VENTA = 1
TIPO_DEPARTAMENTO = 2
MONEDA_USD = 1

CONSULTA = """
query Buscar($p: SearchParamsInput!, $first: Int!, $page: Int) {
  searchListing(params: $p, first: $first, page: $page) {
    paginatorInfo { total currentPage lastPage }
    data {
      id title address code link latitude longitude
      bedrooms bathrooms m2 garage floor construction_year
      price { amount currency { id name } }
      neighborhood { name }
      owner { name }
    }
  }
}
"""


def buscar(dormitorios=(1, 2), precio_max_usd=300_000, por_pagina=100,
           max_paginas=40, log=print, **_):
    """Descarga avisos de venta de departamentos con N dormitorios exactos."""
    avisos = []
    for dorm in dormitorios:
        params = {
            "operation_type_id": OPERACION_VENTA,
            "property_type_id": TIPO_DEPARTAMENTO,
            "bedrooms": dorm,
            "bedroomsExactMode": True,
            "maxPrice": precio_max_usd,
            "currencyID": MONEDA_USD,
        }
        pagina = 1
        while pagina <= max_paginas:
            r = http.post_json(
                ENDPOINT,
                {"query": CONSULTA,
                 "variables": {"p": params, "first": por_pagina, "page": pagina}},
                headers=CABECERAS,
            )
            if "errors" in r:
                raise RuntimeError(r["errors"])
            bloque = r["data"]["searchListing"]
            info = bloque["paginatorInfo"]
            for x in bloque["data"]:
                a = _a_aviso(x)
                if a:
                    avisos.append(a)
            log(f"  {NOMBRE}: {dorm} dorm, pagina {pagina}/{info['lastPage']} "
                f"({info['total']} avisos)")
            if pagina >= info["lastPage"]:
                break
            pagina += 1
    return avisos


def _a_aviso(x):
    if x.get("latitude") in (None, 0) or x.get("longitude") in (None, 0):
        return None
    precio = (x.get("price") or {}).get("amount") or 0
    moneda_txt = (((x.get("price") or {}).get("currency") or {}).get("name") or "").strip()
    link = (x.get("link") or "").lstrip("/")
    return Aviso(
        fuente=NOMBRE,
        id=str(x["id"]),
        titulo=(x.get("title") or "").strip(),
        url=BASE_WEB + link if link else BASE_WEB,
        lat=float(x["latitude"]),
        lon=float(x["longitude"]),
        distrito=(x.get("neighborhood") or {}).get("name") or "",
        direccion=x.get("address") or "",
        dormitorios_min=x.get("bedrooms") or 0,
        dormitorios_max=x.get("bedrooms") or 0,
        banos=x.get("bathrooms") or 0,
        m2=float(x.get("m2") or 0),
        precio=float(precio),
        moneda="PEN" if moneda_txt.startswith("S/") else "USD",
        estacionamiento=x.get("garage") or 0,
        piso=x.get("floor") or 0,
        anio=str(x.get("construction_year") or ""),
        contacto=(x.get("owner") or {}).get("name") or "",
    )
