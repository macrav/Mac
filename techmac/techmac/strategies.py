"""Estrategias. Regla de oro: la señal de la vela i solo usa datos hasta la vela i.

La ejecución ocurre en la apertura de la vela i+1 (lo hace el motor), así que
ninguna estrategia puede "ver el futuro". Un test lo comprueba alterando las
velas futuras y verificando que las señales pasadas no cambian.
"""

import itertools

from . import validate as V

MAX_COMBOS = 200


class Strategy:
    name = ""
    description = ""
    intraday = False
    # nombre -> (defecto, mínimo, máximo, es_entero)
    PARAMS = {}
    GRID = {}

    def __init__(self, **params):
        unknown = set(params) - set(self.PARAMS)
        if unknown:
            raise V.ValidationError("Parámetros desconocidos para %s: %s" % (self.name, ", ".join(sorted(unknown))))
        self.params = {}
        for k, (default, lo, hi, integer) in self.PARAMS.items():
            self.params[k] = V.number(params.get(k, default), k, lo, hi, integer)
        self._prepared_for = None

    def prepare(self, series):
        if self._prepared_for is series:
            return
        if series.intraday != self.intraday:
            raise V.ValidationError("%s requiere velas %s." % (self.name, "intradía" if self.intraday else "diarias (1d)"))
        self.series = series
        self._prepare(series)
        self._prepared_for = series

    def _prepare(self, series):
        raise NotImplementedError

    def entry(self, i):
        """(stop, target|None) si hay señal de compra al cierre de la vela i."""
        return self._sig[i]

    def exit(self, i, pos):
        return False

    def trail(self, i, pos):
        return None

    @classmethod
    def describe(cls):
        return {"name": cls.name, "description": cls.description,
                "bars": "intradía (1m-60m)" if cls.intraday else "diarias (1d)",
                "params": {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi, _i) in cls.PARAMS.items()},
                "default_grid": cls.GRID}


# ---------- indicadores causales ----------

def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def atr(bars, n):
    trs = []
    for i, b in enumerate(bars):
        pc = bars[i - 1].c if i else b.c
        trs.append(max(b.h - b.l, abs(b.h - pc), abs(b.l - pc)))
    return sma(trs, n)


def prev_max(xs, n):
    """Máximo de las n velas ANTERIORES (excluye la actual)."""
    return [max(xs[i - n:i]) if i >= n else None for i in range(len(xs))]


def prev_min(xs, n):
    return [min(xs[i - n:i]) if i >= n else None for i in range(len(xs))]


# ---------- estrategias ----------

class OpeningRangeBreakout(Strategy):
    name = "orb"
    description = ("Ruptura del rango de apertura: compra en la apertura de la vela siguiente al primer cierre "
                   "por encima del máximo de los primeros N minutos. Stop en el medio o el mínimo del rango, "
                   "objetivo en múltiplos de R, cierre obligatorio antes de flat_by. Una operación por día.")
    intraday = True
    PARAMS = {
        "or_minutes": (15, 5, 120, True),
        "stop_at_low": (0, 0, 1, True),        # 0 = medio del rango, 1 = mínimo del rango
        "target_r": (1.0, 0.0, 10.0, False),   # 0 = sin objetivo (sale por flat_by)
        "no_entries_after": (930, 600, 960, True),  # minutos desde medianoche (930 = 15:30)
        "min_range_pct": (0.0, 0.0, 10.0, False),
    }
    GRID = {"or_minutes": [15, 30], "target_r": [1.0, 2.0], "stop_at_low": [0, 1]}

    def _prepare(self, s):
        p = self.params
        step = s.step // 60
        or_end = 570 + p["or_minutes"]
        sig = [None] * len(s)
        cur, orh, orl, taken = None, None, None, False
        for i, b in enumerate(s.bars):
            d, m = s.dates[i], s.minutes[i]
            if d != cur:
                cur, orh, orl, taken = d, None, None, False
            if 570 <= m < or_end:
                orh = b.h if orh is None else max(orh, b.h)
                orl = b.l if orl is None else min(orl, b.l)
                continue
            if m < or_end or orh is None or taken or m + step > p["no_entries_after"]:
                continue
            if b.c > orh:
                taken = True
                if (orh - orl) / orl * 100 < p["min_range_pct"]:
                    continue
                stop = orl if p["stop_at_low"] else (orh + orl) / 2
                risk = b.c - stop
                if risk <= 0:
                    continue
                tgt = b.c + p["target_r"] * risk if p["target_r"] > 0 else None
                sig[i] = (stop, tgt)
        self._sig = sig


class SmaCross(Strategy):
    name = "sma_cross"
    description = ("Cruce de medias (diario): compra cuando la media rápida cruza sobre la lenta, vende cuando "
                   "cruza por debajo. Stop protector inicial a atr_mult x ATR, que sube (trailing) si trail=1.")
    PARAMS = {
        "fast": (20, 2, 200, True),
        "slow": (100, 5, 400, True),
        "atr_n": (14, 2, 100, True),
        "atr_mult": (3.0, 0.5, 10.0, False),
        "trail": (1, 0, 1, True),
    }
    GRID = {"fast": [10, 20, 50], "slow": [100, 200], "atr_mult": [2.0, 3.0]}

    def _prepare(self, s):
        p = self.params
        if p["fast"] >= p["slow"]:
            raise V.ValidationError("fast debe ser menor que slow.")
        c = [b.c for b in s.bars]
        self.f, self.s_ = sma(c, p["fast"]), sma(c, p["slow"])
        self.a = atr(s.bars, p["atr_n"])
        sig = [None] * len(c)
        for i in range(1, len(c)):
            if None in (self.f[i - 1], self.s_[i - 1], self.a[i]):
                continue
            if self.f[i - 1] <= self.s_[i - 1] and self.f[i] > self.s_[i]:
                sig[i] = (c[i] - p["atr_mult"] * self.a[i], None)
        self._sig = sig

    def exit(self, i, pos):
        return self.f[i] is not None and self.f[i] < self.s_[i]

    def trail(self, i, pos):
        if self.params["trail"] and self.a[i] is not None:
            return self.series.bars[i].c - self.params["atr_mult"] * self.a[i]
        return None


class Donchian(Strategy):
    name = "donchian"
    description = ("Ruptura de canal (diario, estilo tortuga): compra al cerrar sobre el máximo de N días, vende "
                   "al cerrar bajo el mínimo de M días. Stop protector inicial a atr_mult x ATR.")
    PARAMS = {
        "entry_n": (55, 5, 400, True),
        "exit_n": (20, 2, 200, True),
        "atr_n": (20, 2, 100, True),
        "atr_mult": (2.0, 0.5, 10.0, False),
    }
    GRID = {"entry_n": [20, 55, 100], "exit_n": [10, 20], "atr_mult": [2.0, 3.0]}

    def _prepare(self, s):
        p = self.params
        c = [b.c for b in s.bars]
        hh = prev_max([b.h for b in s.bars], p["entry_n"])
        self.ll = prev_min([b.l for b in s.bars], p["exit_n"])
        a = atr(s.bars, p["atr_n"])
        self._sig = [(c[i] - p["atr_mult"] * a[i], None) if hh[i] is not None and a[i] is not None and c[i] > hh[i]
                     else None for i in range(len(c))]

    def exit(self, i, pos):
        return self.ll[i] is not None and self.series.bars[i].c < self.ll[i]


def rsi(xs, n):
    """RSI de Wilder, causal."""
    out = [None] * len(xs)
    if len(xs) <= n:
        return out
    gains = [max(0.0, xs[i] - xs[i - 1]) for i in range(1, len(xs))]
    losses = [max(0.0, xs[i - 1] - xs[i]) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(xs)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


class Rsi2(Strategy):
    name = "rsi2"
    description = ("Reversión a la media de Larry Connors (RSI de 2 días): compra cuando el RSI(2) cae bajo el umbral "
                   "y el precio está sobre su media de 200 días (solo retrocesos dentro de tendencia alcista). Sale "
                   "cuando cierra sobre la media corta o tras max_hold días. Stop de emergencia a atr_mult x ATR.")
    PARAMS = {
        "rsi_n": (2, 2, 14, True),
        "entry_below": (10.0, 1.0, 40.0, False),
        "trend_n": (200, 20, 400, True),
        "exit_sma": (5, 2, 50, True),
        "max_hold": (10, 1, 60, True),
        "atr_mult": (4.0, 0.5, 10.0, False),
    }
    GRID = {"entry_below": [5.0, 10.0, 15.0], "exit_sma": [5, 10]}

    def _prepare(self, s):
        p = self.params
        c = [b.c for b in s.bars]
        r = rsi(c, p["rsi_n"])
        t = sma(c, p["trend_n"])
        self.ex = sma(c, p["exit_sma"])
        a = atr(s.bars, 14)
        self._sig = [(c[i] - p["atr_mult"] * a[i], None)
                     if None not in (r[i], t[i], a[i]) and r[i] < p["entry_below"] and c[i] > t[i] else None
                     for i in range(len(c))]

    def exit(self, i, pos):
        return ((self.ex[i] is not None and self.series.bars[i].c > self.ex[i])
                or i - pos.i_entry + 1 >= self.params["max_hold"])


class Ibs(Strategy):
    name = "ibs"
    description = ("Internal Bar Strength: IBS = (cierre - mínimo) / (máximo - mínimo). Compra cuando el día cierra "
                   "cerca de su mínimo (IBS bajo) con el precio sobre su media de tendencia; sale cuando el IBS sube "
                   "sobre exit_above o tras max_hold días. Efecto documentado en índices bursátiles.")
    PARAMS = {
        "entry_below": (0.2, 0.01, 0.5, False),
        "exit_above": (0.8, 0.3, 0.99, False),
        "trend_n": (200, 0, 400, True),       # 0 = sin filtro de tendencia
        "max_hold": (5, 1, 30, True),
        "atr_mult": (4.0, 0.5, 10.0, False),
    }
    GRID = {"entry_below": [0.1, 0.2, 0.3], "exit_above": [0.5, 0.8]}

    def _prepare(self, s):
        p = self.params
        c = [b.c for b in s.bars]
        self.ibs = [(b.c - b.l) / (b.h - b.l) if b.h > b.l else 0.5 for b in s.bars]
        t = sma(c, p["trend_n"]) if p["trend_n"] else [0.0] * len(c)
        a = atr(s.bars, 14)
        self._sig = [(c[i] - p["atr_mult"] * a[i], None)
                     if t[i] is not None and a[i] is not None and self.ibs[i] < p["entry_below"] and c[i] > t[i]
                     else None for i in range(len(c))]

    def exit(self, i, pos):
        return self.ibs[i] > self.params["exit_above"] or i - pos.i_entry + 1 >= self.params["max_hold"]


class TrendFilter(Strategy):
    name = "trend_filter"
    description = ("Filtro de tendencia de Meb Faber: invertido mientras el precio está sobre su media de N días, "
                   "fuera cuando cae bajo la media menos una banda (evita entrar y salir por ruido). Su objetivo no "
                   "es ganarle al índice en retorno sino recortar las grandes caídas.")
    PARAMS = {
        "sma_n": (200, 20, 400, True),
        "band_pct": (1.0, 0.0, 10.0, False),
        "atr_mult": (6.0, 1.0, 20.0, False),
    }
    GRID = {"sma_n": [100, 150, 200], "band_pct": [0.0, 2.0]}

    def _prepare(self, s):
        p = self.params
        c = [b.c for b in s.bars]
        self.m = sma(c, p["sma_n"])
        a = atr(s.bars, 20)
        self._sig = [(c[i] - p["atr_mult"] * a[i], None)
                     if self.m[i] is not None and a[i] is not None and c[i] > self.m[i] * (1 + p["band_pct"] / 100)
                     else None for i in range(len(c))]

    def exit(self, i, pos):
        m = self.m[i]
        return m is not None and self.series.bars[i].c < m * (1 - self.params["band_pct"] / 100)


class TimeSeriesMomentum(Strategy):
    name = "tsmom"
    description = ("Momentum de serie temporal (Moskowitz, Ooi y Pedersen, 2012): invertido mientras el retorno de los "
                   "últimos N días es positivo, fuera cuando es negativo. Es la base de los fondos de seguimiento "
                   "de tendencia (CTA).")
    PARAMS = {
        "lookback": (252, 20, 504, True),
        "atr_mult": (6.0, 1.0, 20.0, False),
    }
    GRID = {"lookback": [63, 126, 252], "atr_mult": [4.0, 8.0]}

    def _prepare(self, s):
        p, n = self.params, self.params["lookback"]
        c = [b.c for b in s.bars]
        self.mom = [c[i] / c[i - n] - 1 if i >= n else None for i in range(len(c))]
        a = atr(s.bars, 20)
        self._sig = [(c[i] - p["atr_mult"] * a[i], None)
                     if self.mom[i] is not None and a[i] is not None and self.mom[i] > 0 else None
                     for i in range(len(c))]

    def exit(self, i, pos):
        return self.mom[i] is not None and self.mom[i] < 0


REGISTRY = {cls.name: cls for cls in (OpeningRangeBreakout, SmaCross, Donchian, Rsi2, Ibs, TrendFilter,
                                       TimeSeriesMomentum)}


def get(name):
    if name not in REGISTRY:
        raise V.ValidationError("Estrategia desconocida: %r (opciones: %s)" % (name, ", ".join(REGISTRY)))
    return REGISTRY[name]


def expand_grid(cls, grid=None):
    grid = cls.GRID if grid is None else grid
    if not isinstance(grid, dict) or not grid:
        raise V.ValidationError("La rejilla debe ser un objeto {parámetro: [valores]}.")
    keys = sorted(grid)
    for k in keys:
        if k not in cls.PARAMS:
            raise V.ValidationError("Parámetro desconocido en la rejilla: %s" % k)
        if not isinstance(grid[k], list) or not grid[k] or len(grid[k]) > 20:
            raise V.ValidationError("La rejilla de %s debe ser una lista de 1 a 20 valores." % k)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]
    if len(combos) > MAX_COMBOS:
        raise V.ValidationError("Demasiadas combinaciones (%d > %d)." % (len(combos), MAX_COMBOS))
    out = []
    for c in combos:
        try:
            strat = cls(**c)
            if cls is SmaCross and strat.params["fast"] >= strat.params["slow"]:
                continue
            out.append(strat)
        except V.ValidationError:
            raise
    return out
