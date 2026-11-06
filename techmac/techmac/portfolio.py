"""Portafolios multi-activo con rebalanceo mensual: la forma en que invierten los grandes fondos globales.

Reglas de ejecución (conservadoras):
- Los pesos se deciden con el cierre del último día hábil del mes (solo datos hasta ese día)
  y se ejecutan al cierre del día hábil SIGUIENTE (un día de retraso).
- Costo por rotación: (slippage + medio spread) x 2 por cada dólar que se mueve, x cost_mult.
- El efectivo no rinde nada (conservador). Usa un ETF de bonos cortos como activo seguro.
- El apalancamiento está apagado por defecto (max_leverage = 1). Si se activa, se cobra financiación.
"""

import itertools
import math
import statistics

from . import metrics as M
from . import validate as V
from .store import Store


class Panel:
    """Cierres ajustados alineados en las fechas comunes a todos los activos."""

    def __init__(self, symbols, dates, closes):
        self.symbols, self.dates, self.closes = symbols, dates, closes
        self.k = len(symbols)
        self.rets = [[0.0] * self.k] + [[closes[t][j] / closes[t - 1][j] - 1 for j in range(self.k)]
                                        for t in range(1, len(dates))]
        self.month_end = [t + 1 == len(dates) or dates[t + 1].month != dates[t].month for t in range(len(dates))]

    def fingerprint(self):
        import hashlib
        h = hashlib.sha256(",".join(self.symbols).encode())
        for d, row in zip(self.dates, self.closes):
            h.update(("%s:%s;" % (d, ",".join("%.6f" % x for x in row))).encode())
        return h.hexdigest()


def load_panel(h, symbols, start=None, end=None):
    if not isinstance(symbols, list) or not 2 <= len(symbols) <= 30:
        raise V.ValidationError("Un portafolio necesita de 2 a 30 símbolos.")
    symbols = [V.symbol(s) for s in symbols]
    if len(set(symbols)) != len(symbols):
        raise V.ValidationError("Hay símbolos repetidos.")
    st = Store(h)
    try:
        maps = []
        for s in symbols:
            ser = st.load(s, "1d", V.date(start) if start else None, V.date(end) if end else None)
            if len(ser) < 300:
                raise V.ValidationError("Faltan datos diarios de %s (hay %d velas). Corre: tm.py fetch %s" % (s, len(ser), s))
            maps.append({d: b.c for d, b in zip(ser.dates, ser.bars)})
    finally:
        st.close()
    common = sorted(set.intersection(*(set(m) for m in maps)))
    if len(common) < 756:
        raise V.ValidationError("Solo hay %d días en común entre los activos (mínimo 756)." % len(common))
    return Panel(symbols, common, [[m[d] for m in maps] for d in common])


# ---------- estrategias de asignación ----------
# Cada una devuelve {índice_activo: peso} usando solo datos hasta t. La suma puede ser < 1 (resto en efectivo).

def _ret(p, t, j, n):
    return p.closes[t][j] / p.closes[t - n][j] - 1 if t >= n else None


def _vol(p, t, j, n):
    if t < n + 1:
        return None
    xs = [p.rets[s][j] for s in range(t - n + 1, t + 1)]
    v = statistics.pstdev(xs)
    return v if v > 0 else None


def _sma_above(p, t, j, n):
    if t < n:
        return None
    return p.closes[t][j] > sum(p.closes[s][j] for s in range(t - n + 1, t + 1)) / n


class Allocation:
    name, description = "", ""
    PARAMS, GRID = {}, {}
    uses_safe = True

    def __init__(self, **params):
        unknown = set(params) - set(self.PARAMS)
        if unknown:
            raise V.ValidationError("Parámetros desconocidos para %s: %s" % (self.name, ", ".join(sorted(unknown))))
        self.params = {k: V.number(params.get(k, d), k, lo, hi, integer)
                       for k, (d, lo, hi, integer) in self.PARAMS.items()}

    @classmethod
    def describe(cls):
        return {"name": cls.name, "description": cls.description,
                "params": {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi, _i) in cls.PARAMS.items()},
                "default_grid": cls.GRID}

    def weights(self, p, t, safe):
        raise NotImplementedError


class EqualWeight(Allocation):
    name = "equal_weight"
    description = "Mismo peso en todos los activos, rebalanceo mensual. Referencia simple y difícil de batir."
    uses_safe = False
    GRID = {}

    def weights(self, p, t, safe):
        return {j: 1.0 / p.k for j in range(p.k)}


class RiskParity(Allocation):
    name = "risk_parity"
    description = ("Paridad de riesgo (idea de Bridgewater All Weather): cada activo pesa en proporción inversa a su "
                   "volatilidad, para que todos aporten un riesgo parecido.")
    uses_safe = False
    PARAMS = {"vol_n": (63, 10, 252, True)}
    GRID = {"vol_n": [21, 63, 126]}

    def weights(self, p, t, safe):
        inv = {j: 1 / v for j in range(p.k) for v in [_vol(p, t, j, self.params["vol_n"])] if v}
        tot = sum(inv.values())
        return {j: x / tot for j, x in inv.items()} if tot else {}


class DualMomentum(Allocation):
    name = "dual_momentum"
    description = ("Momentum Dual de Gary Antonacci (GEM): invierte todo en el activo de riesgo con mejor retorno de "
                   "los últimos N días; si ese retorno es negativo (momentum absoluto), se pasa al activo seguro.")
    PARAMS = {"lookback": (252, 21, 504, True)}
    GRID = {"lookback": [126, 189, 252]}

    def weights(self, p, t, safe):
        n = self.params["lookback"]
        risky = [j for j in range(p.k) if j != safe]
        rs = [(r, j) for j in risky for r in [_ret(p, t, j, n)] if r is not None]
        if not rs:
            return {}
        best_r, best = max(rs)
        return {best: 1.0} if best_r > 0 else ({safe: 1.0} if safe is not None else {})


class RelativeMomentum(Allocation):
    name = "relative_momentum"
    description = ("Rotación por momentum relativo (Jegadeesh y Titman; Faber): reparte en partes iguales entre los "
                   "top_n activos con mejor retorno de N días. Cada parte con retorno negativo va al activo seguro.")
    PARAMS = {"lookback": (126, 21, 504, True), "top_n": (2, 1, 10, True)}
    GRID = {"lookback": [63, 126, 252], "top_n": [1, 2, 3]}

    def weights(self, p, t, safe):
        n, top = self.params["lookback"], self.params["top_n"]
        risky = [j for j in range(p.k) if j != safe]
        rs = sorted(((r, j) for j in risky for r in [_ret(p, t, j, n)] if r is not None), reverse=True)[:top]
        w = {}
        for r, j in rs:
            dest = j if r > 0 else safe
            if dest is not None:
                w[dest] = w.get(dest, 0.0) + 1.0 / top
        return w


class TrendParity(Allocation):
    name = "trend_parity"
    description = ("Tendencia + paridad de riesgo (estilo GTAA de Faber): pesos inversos a la volatilidad, pero cada "
                   "activo bajo su media de N días cede su parte al activo seguro. Busca recortar las caídas grandes.")
    PARAMS = {"sma_n": (200, 20, 400, True), "vol_n": (63, 10, 252, True)}
    GRID = {"sma_n": [100, 200], "vol_n": [21, 63]}

    def weights(self, p, t, safe):
        risky = [j for j in range(p.k) if j != safe]
        inv = {j: 1 / v for j in risky for v in [_vol(p, t, j, self.params["vol_n"])] if v}
        tot = sum(inv.values())
        if not tot:
            return {}
        w = {}
        for j, x in inv.items():
            above = _sma_above(p, t, j, self.params["sma_n"])
            dest = j if above else safe
            if dest is not None:
                w[dest] = w.get(dest, 0.0) + x / tot
        return w


ALLOCATIONS = {c.name: c for c in (EqualWeight, RiskParity, DualMomentum, RelativeMomentum, TrendParity)}


def get(name):
    if name not in ALLOCATIONS:
        raise V.ValidationError("Asignación desconocida: %r (opciones: %s)" % (name, ", ".join(ALLOCATIONS)))
    return ALLOCATIONS[name]


def expand(cls, grid=None):
    grid = cls.GRID if grid is None else grid
    if not grid:
        return [cls()]
    keys = sorted(grid)
    for k in keys:
        if k not in cls.PARAMS or not isinstance(grid[k], list) or not 1 <= len(grid[k]) <= 20:
            raise V.ValidationError("Rejilla inválida para %s." % k)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    if len(combos) > 200:
        raise V.ValidationError("Demasiadas combinaciones.")
    return [cls(**dict(zip(keys, c))) for c in combos]


# ---------- motor ----------

class PortfolioConfig:
    def __init__(self, cost_bps=6.0, cost_mult=1.0, target_vol=0.0, max_leverage=1.0, borrow_rate=0.06,
                 initial=10000.0):
        self.cost_bps = V.number(cost_bps, "cost_bps", 0, 500)
        self.cost_mult = cost_mult
        self.target_vol = V.number(target_vol, "target_vol", 0, 100)
        self.max_leverage = V.number(max_leverage, "max_leverage", 0.1, 3.0)
        self.borrow_rate = borrow_rate
        self.initial = initial

    @classmethod
    def from_config(cls, cfg, target_vol=0.0, max_leverage=1.0):
        c = cfg["costs"]
        return cls(c["slippage_bps"] + c["spread_bps"] / 2, 1.0, target_vol, max_leverage,
                   initial=cfg["backtest"]["initial_equity"])

    def stressed(self, mult):
        return PortfolioConfig(self.cost_bps, mult, self.target_vol, self.max_leverage, self.borrow_rate, self.initial)


def _vol_scale(p, t, w, cfg):
    """Escala la exposición para apuntar a target_vol anual (0 = apagado)."""
    if not cfg.target_vol or t < 64:
        return 1.0
    xs = [sum(w.get(j, 0) * p.rets[s][j] for j in range(p.k)) for s in range(t - 62, t + 1)]
    v = statistics.pstdev(xs) * math.sqrt(252)
    return min(cfg.max_leverage, cfg.target_vol / 100.0 / v) if v > 0 else 1.0


def run(p, chooser, safe, cfg, start, end):
    """chooser(t) -> estrategia de asignación activa en t (o None = efectivo)."""
    w = [0.0] * p.k
    eq = cfg.initial
    pending = None
    equity, turnover = [], 0.0
    cost = cfg.cost_bps * cfg.cost_mult / 1e4
    for t in range(start, end):
        if t > start:
            gross = sum(w)
            day = sum(w[j] * p.rets[t][j] for j in range(p.k))
            if gross > 1:
                day -= (gross - 1) * cfg.borrow_rate / 252
            eq *= 1 + day
            if eq <= 0:
                equity.append((p.dates[t], 0.0))
                break
            if 1 + day != 0:
                w = [w[j] * (1 + p.rets[t][j]) / (1 + day) for j in range(p.k)]
        if pending is not None:
            moved = sum(abs(pending[j] - w[j]) for j in range(p.k))
            eq -= eq * moved * cost
            turnover += moved
            w, pending = pending, None
        if p.month_end[t] and t + 1 < end:
            strat = chooser(t)
            target = strat.weights(p, t, safe) if strat is not None else {}
            scale = _vol_scale(p, t, target, cfg)
            pending = [target.get(j, 0.0) * scale for j in range(p.k)]
        equity.append((p.dates[t], eq))
    years = max(1e-9, (end - start) / 252)
    return equity, turnover / years


def monthly_returns(equity):
    out, last_m, last_v, prev = [], None, None, None
    for d, v in equity:
        key = (d.year, d.month)
        if last_m is not None and key != last_m:
            if prev is not None:
                out.append(last_v / prev - 1)
            prev = last_v
        last_m, last_v = key, v
    if prev is not None and last_v is not None:
        out.append(last_v / prev - 1)
    return out


def evaluate(p, cls, grid, safe_symbol, cfg, criteria, train_years=5, test_years=1, benchmark=None, extra_trials=0):
    safe = None
    if cls.uses_safe:
        if not safe_symbol:
            raise V.ValidationError("%s necesita un activo seguro (--safe, p. ej. SHY o IEF)." % cls.name)
        safe_symbol = V.symbol(safe_symbol)
        if safe_symbol not in p.symbols:
            raise V.ValidationError("El activo seguro %s debe estar en la lista de símbolos." % safe_symbol)
        safe = p.symbols.index(safe_symbol)
    bench = V.symbol(benchmark) if benchmark else p.symbols[0]
    if bench not in p.symbols:
        raise V.ValidationError("El benchmark debe estar en la lista de símbolos.")
    combos = expand(cls, grid)
    tr = int(V.number(train_years, "train_years", 1, 30, True)) * 252
    te = int(V.number(test_years, "test_years", 1, 10, True)) * 252
    warm = 260
    segs, folds, fold_vars = [], [], []
    k = warm
    while k + tr + 21 <= len(p.dates):             # la última ventana puede ser parcial (>= 1 mes)
        te_end = min(k + tr + te, len(p.dates))
        best, best_sr, srs = None, -math.inf, []
        for st in combos:
            eq, _ = run(p, lambda t, st=st: st, safe, cfg, k, k + tr)
            sr = M.sharpe(M.daily_returns(eq, cfg.initial))
            srs.append(sr)
            if sr > best_sr:
                best, best_sr = st, sr
        if len(srs) > 1:
            fold_vars.append(statistics.pvariance(srs))
        segs.append((k + tr, te_end, best))
        folds.append({"train": [str(p.dates[k]), str(p.dates[k + tr - 1])],
                      "test": [str(p.dates[k + tr]), str(p.dates[te_end - 1])],
                      "params": best.params, "train_sharpe_annual": round(best_sr * math.sqrt(252), 3)})
        k += te
    if not segs:
        raise V.ValidationError("Datos insuficientes: hacen falta %d años en común y hay %.1f."
                                % ((warm + tr + te) // 252, len(p.dates) / 252))
    a, b = segs[0][0], segs[-1][1]

    def chooser(t):
        for s0, s1, st in segs:
            if s0 <= t < s1:
                return st
        return None

    eq, turn = run(p, chooser, safe, cfg, a, b)
    eq2, _ = run(p, chooser, safe, cfg.stressed(2.0), a, b)
    j = p.symbols.index(bench)
    bh = [(p.dates[t], p.closes[t][j] / p.closes[a][j]) for t in range(a, b)]
    ew_eq, _ = run(p, lambda t: EqualWeight(), None, cfg, a, b)
    rets = M.daily_returns(eq, cfg.initial)
    n_trials = len(combos) + int(extra_trials)
    dsr = M.dsr(rets, n_trials, statistics.fmean(fold_vars) if fold_vars else 0.0)
    oos = M.equity_stats(eq, cfg.initial)
    stress = M.equity_stats(eq2, cfg.initial)
    bstats = M.equity_stats(bh, 1.0)
    ew = M.equity_stats(ew_eq, cfg.initial)
    years = (b - a) / 252
    checks = []

    def add(name, value, rule, ok):
        checks.append({"check": name, "value": value, "rule": rule, "pass": bool(ok)})

    add("Años fuera de muestra", round(years, 1), ">= %s" % criteria["min_oos_years"], years >= criteria["min_oos_years"])
    add("Deflated Sharpe Ratio", round(dsr, 3), ">= %s" % criteria["min_dsr"], dsr >= criteria["min_dsr"])
    add("Sharpe vs %s comprar y mantener" % bench, "%s vs %s" % (oos["sharpe_annual"], bstats["sharpe_annual"]),
        "mayor", oos["sharpe_annual"] > bstats["sharpe_annual"])
    add("Sharpe con costos x2 vs %s" % bench, "%s vs %s" % (stress["sharpe_annual"], bstats["sharpe_annual"]),
        "mayor", stress["sharpe_annual"] > bstats["sharpe_annual"])
    add("Máxima caída", "%s %%" % oos["max_drawdown_pct"], "<= %s %%" % criteria["max_dd_portfolio_pct"],
        oos["max_drawdown_pct"] <= criteria["max_dd_portfolio_pct"])
    ok = all(c["pass"] for c in checks)
    last_t = len(p.dates) - 1
    current = chooser(min(last_t, b - 1)) or best
    now = current.weights(p, last_t, safe)
    now = {p.symbols[j]: round(w * _vol_scale(p, last_t, now, cfg), 4) for j, w in now.items() if w > 0}
    return {
        "symbol": "PORT:" + ",".join(p.symbols), "interval": "1d", "strategy": cls.name, "kind": "portfolio",
        "data": {"first": str(p.dates[0]), "last": str(p.dates[-1]), "sessions": len(p.dates),
                 "fingerprint": p.fingerprint()},
        "setup": {"symbols": p.symbols, "safe": p.symbols[safe] if safe is not None else None, "benchmark": bench,
                  "train_years": train_years, "test_years": test_years, "combos_tested": len(combos),
                  "trials_counted_for_dsr": n_trials, "cost_bps_per_side": cfg.cost_bps,
                  "target_vol_pct": cfg.target_vol, "max_leverage": cfg.max_leverage},
        "out_of_sample": {"period": [str(p.dates[a]), str(p.dates[b - 1])], "equity": oos, "dsr": round(dsr, 4),
                          "turnover_per_year": round(turn, 2)},
        "stress_costs_x2": stress,
        "benchmark_buy_and_hold": bstats,
        "equal_weight_same_assets": ew,
        "oos_monthly_returns": [round(x, 6) for x in monthly_returns(eq)],
        "current_target_weights": {"as_of": str(p.dates[last_t]), "params": current.params, "weights": now,
                                   "cash": round(max(0.0, 1 - sum(now.values())), 4)},
        "folds": folds,
        "verdict": {"pass": ok, "label": "APROBADA para prueba en papel" if ok else "RECHAZADA",
                    "meaning": ("Pasó todos los filtros fuera de muestra. Úsala en papel varios meses antes de "
                                "dinero real." if ok else
                                "No supera con evidencia suficiente a simplemente comprar y mantener %s." % bench),
                    "checks": checks},
    }
