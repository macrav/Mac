"""Descarga opcional de datos públicos. ÚNICO módulo de TechMaC que usa la red.

- Solo HTTPS y solo hosts de la lista blanca (también en redirecciones).
- Tamaño máximo de respuesta y tiempo límite.
- Solo lectura: nunca envía datos tuyos, ni claves, ni órdenes.
- El servidor MCP no lo importa: Claude no puede descargar nada a través del conector.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import validate as V
from .store import Bar, parse_csv

ALLOWED_HOSTS = {"query1.finance.yahoo.com", "query2.finance.yahoo.com", "stooq.com"}
MAX_BYTES = 30 * 1024 * 1024
TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (TechMaC local backtester)"


class FetchError(RuntimeError):
    pass


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS:
        raise FetchError("URL bloqueada por la lista blanca: %s" % url)


def _get(url):
    _check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise FetchError("HTTP %s en %s" % (e.code, urllib.parse.urlsplit(url).hostname))
    except urllib.error.URLError as e:
        raise FetchError("Sin conexión: %s" % e.reason)
    if len(data) > MAX_BYTES:
        raise FetchError("Respuesta demasiado grande.")
    return data


YAHOO_RANGE = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "60m": "730d", "1d": "max"}


def yahoo(symbol, interval):
    """Velas de Yahoo. Diario: ajustado por splits y dividendos con adjclose."""
    symbol, interval = V.symbol(symbol), V.interval(interval)
    params = {"interval": interval, "includePrePost": "false", "events": "div,splits"}
    if interval == "1d":
        # range=max devuelve velas MENSUALES; con period1/period2 sí llegan diarias
        params.update(period1="0", period2=str(int(time.time()) + 86400))
    else:
        params["range"] = YAHOO_RANGE[interval]
    q = urllib.parse.urlencode(params)
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?%s" % (urllib.parse.quote(symbol, safe=""), q)
    raw = _get(url)
    try:
        doc = json.loads(raw)
        res = doc["chart"]["result"][0]
        ts = res.get("timestamp") or []
        quote = res["indicators"]["quote"][0]
        adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    except (ValueError, KeyError, IndexError, TypeError):
        err = None
        try:
            err = json.loads(raw)["chart"]["error"]
        except Exception:
            pass
        raise FetchError("Respuesta de Yahoo inesperada%s" % (": %s" % err if err else ""))
    bars = []
    for k, t in enumerate(ts):
        o, h, l, c, v = (quote.get(x, [None] * len(ts))[k] for x in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        f = 1.0
        if interval == "1d" and adj and adj[k] and c:
            f = adj[k] / c
        bars.append(Bar(int(t), o * f, h * f, l * f, c * f, float(v or 0)))
    _check_spacing(bars, interval)
    return bars, raw


def _check_spacing(bars, interval):
    """Rechaza respuestas con velas más espaciadas de lo pedido (p. ej. mensuales en vez de diarias)."""
    if len(bars) < 20:
        return
    gaps = sorted(b.ts - a.ts for a, b in zip(bars, bars[1:]))
    median = gaps[len(gaps) // 2]
    limit = 4 * 86400 if interval == "1d" else V.INTERVALS[interval] * 2
    if median > limit:
        raise FetchError("Yahoo devolvió velas de ~%d horas en vez de %s; no se guardó nada." % (median // 3600, interval))


def stooq(symbol):
    """Velas diarias de Stooq (CSV). Acciones de EE. UU.: AAPL -> aapl.us"""
    symbol = V.symbol(symbol)
    s = symbol.lower() if "." in symbol else symbol.lower() + ".us"
    url = "https://stooq.com/q/d/l/?" + urllib.parse.urlencode({"s": s, "i": "d"})
    raw = _get(url)
    if not raw.lstrip().lower().startswith(b"date"):
        raise FetchError("Stooq no devolvió un CSV (puede pedir clave o no tener el símbolo).")
    bars, _bad = parse_csv(raw, "1d", "UTC")
    return bars, raw
