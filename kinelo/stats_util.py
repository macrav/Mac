"""
Funciones estadísticas mínimas, sin dependencias externas.

Solo hace falta la cola superior de la chi-cuadrado y la normal, así que se
implementan directo en vez de arrastrar scipy. Los valores coinciden con
scipy.stats hasta ~1e-12 en el rango que usamos.
"""

import math

_MAX_ITER = 500
_EPS = 1e-14


def _lower_gamma_series(s: float, x: float) -> float:
    """Serie para P(s,x) = gamma_inf(s,x)/Gamma(s), buena cuando x < s+1."""
    term = 1.0 / s
    total = term
    for n in range(1, _MAX_ITER):
        term *= x / (s + n)
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + s * math.log(x) - math.lgamma(s))


def _upper_gamma_cf(s: float, x: float) -> float:
    """Fracción continua para Q(s,x), buena cuando x >= s+1."""
    tiny = 1e-300
    b = x + 1.0 - s
    c = 1.0 / tiny
    d = 1.0 / b if b else 1.0 / tiny
    h = d
    for i in range(1, _MAX_ITER):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h * math.exp(-x + s * math.log(x) - math.lgamma(s))


def gammainc_upper(s: float, x: float) -> float:
    """Q(s,x): gamma incompleta superior regularizada."""
    if x < 0 or s <= 0:
        raise ValueError("parámetros inválidos")
    if x == 0:
        return 1.0
    if x < s + 1.0:
        return 1.0 - _lower_gamma_series(s, x)
    return _upper_gamma_cf(s, x)


def chi2_sf(statistic: float, df: int) -> float:
    """p-valor de una chi-cuadrado: P(X^2 >= statistic) con df grados de libertad."""
    if statistic <= 0:
        return 1.0
    return gammainc_upper(df / 2.0, statistic / 2.0)


def normal_sf(z: float) -> float:
    """Cola superior de la normal estándar."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_sided_normal_p(z: float) -> float:
    return 2.0 * normal_sf(abs(z))


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """
    Corrección por comparaciones múltiples (FDR).

    Cuando se corren 80 tests a la vez, ~4 salen "significativos" al 5% solo
    por azar. Sin esta corrección, cualquiera "descubre" números calientes.
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    rejected = [False] * m
    max_k = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= alpha * rank / m:
            max_k = rank
    if max_k > 0:
        for rank, idx in enumerate(order, start=1):
            if rank <= max_k:
                rejected[idx] = True
    return rejected
