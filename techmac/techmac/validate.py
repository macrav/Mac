"""Validación estricta de todo lo que entra a TechMaC (CLI, MCP, CSV)."""

import datetime as dt
import math
import re

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,14}$")
INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1d": 86400}


class ValidationError(ValueError):
    pass


def symbol(value):
    if not isinstance(value, str):
        raise ValidationError("El símbolo debe ser texto.")
    s = value.strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValidationError("Símbolo inválido: %r" % value)
    return s


def interval(value):
    if value not in INTERVALS:
        raise ValidationError("Intervalo inválido: %r (usa uno de %s)" % (value, ", ".join(INTERVALS)))
    return value


def number(value, name, lo=None, hi=None, integer=False):
    if isinstance(value, bool) or value is None:
        raise ValidationError("%s debe ser un número." % name)
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValidationError("%s debe ser un número." % name)
    if not math.isfinite(x):
        raise ValidationError("%s debe ser finito." % name)
    if integer:
        if x != int(x):
            raise ValidationError("%s debe ser entero." % name)
        x = int(x)
    if lo is not None and x < lo:
        raise ValidationError("%s debe ser >= %s." % (name, lo))
    if hi is not None and x > hi:
        raise ValidationError("%s debe ser <= %s." % (name, hi))
    return x


def date(value, name="fecha"):
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        raise ValidationError("%s debe ser AAAA-MM-DD." % name)
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        raise ValidationError("%s debe ser AAAA-MM-DD." % name)


def hhmm(value, name="hora"):
    """'15:55' -> minutos desde medianoche."""
    if not isinstance(value, str) or not re.match(r"^\d{1,2}:\d{2}$", value.strip()):
        raise ValidationError("%s debe ser HH:MM." % name)
    h, m = value.strip().split(":")
    h, m = int(h), int(m)
    if h > 23 or m > 59:
        raise ValidationError("%s fuera de rango." % name)
    return h * 60 + m


def text(value, name, max_len=500):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("%s debe ser texto." % name)
    if len(value) > max_len:
        raise ValidationError("%s es demasiado largo (máx. %d)." % (name, max_len))
    return "".join(ch for ch in value if ch.isprintable())
