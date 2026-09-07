"""Cliente HTTP minimo (solo libreria estandar) con reintentos."""

import gzip
import json
import time
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _abrir(req, timeout):
    resp = urllib.request.urlopen(req, timeout=timeout)
    datos = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        datos = gzip.decompress(datos)
    return datos


def get(url: str, headers: dict = None, timeout: int = 90, intentos: int = 4) -> bytes:
    h = {"User-Agent": UA, "Accept-Language": "es-PE,es;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return _con_reintentos(req, timeout, intentos)


def post_json(url: str, payload: dict, headers: dict = None,
              timeout: int = 90, intentos: int = 4) -> dict:
    h = {"User-Agent": UA, "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST"
    )
    return json.loads(_con_reintentos(req, timeout, intentos))


def _con_reintentos(req, timeout, intentos):
    espera = 2
    ultimo = None
    for i in range(intentos):
        try:
            return _abrir(req, timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            ultimo = e
            if i == intentos - 1:
                break
            time.sleep(espera)
            espera *= 2
    raise ultimo
