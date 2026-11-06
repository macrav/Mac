"""Walk-forward, Monte Carlo por bloques, estrés de costos y veredicto."""

import math
import random
import statistics

from . import engine as E
from . import metrics as M
from . import strategies as S
from . import validate as V
from .portfolio import monthly_returns


def _date_bounds(series):
    """fecha -> (primer índice, índice fin exclusivo)."""
    bounds, order = {}, []
    for i, d in enumerate(series.dates):
        if d not in bounds:
            bounds[d] = [i, i + 1]
            order.append(d)
        else:
            bounds[d][1] = i + 1
    return order, bounds


class _WalkForwardStrategy(S.Strategy):
    """Delega cada vela a la estrategia elegida para su ventana de prueba (posiciones continúan entre ventanas)."""
    name = "walk_forward"

    def __init__(self, segments, intraday):
        self.params, self._prepared_for = {}, None
        self.segments, self.intraday = segments, intraday

    def _prepare(self, s):
        self.owner = [None] * len(s)
        for a, b, st in self.segments:
            for i in range(a, b):
                self.owner[i] = st

    def entry(self, i):
        st = self.owner[i]
        return st.entry(i) if st is not None else None

    def exit(self, i, pos):
        st = self.owner[i]
        return st.exit(i, pos) if st is not None else True   # ventana sin parámetros válidos: quedarse fuera

    def trail(self, i, pos):
        st = self.owner[i]
        return st.trail(i, pos) if st is not None else None


def walk_forward(series, strat_cls, grid, ecfg, train_days, test_days, min_train_trades=None):
    """Optimiza en entrenamiento, opera la ventana siguiente nunca vista, avanza. Una sola simulación continua."""
    train_days = int(V.number(train_days, "train_days", 5, 10000, True))
    test_days = int(V.number(test_days, "test_days", 1, 5000, True))
    if min_train_trades is None:
        min_train_trades = 10 if series.intraday else 3
    combos = S.expand_grid(strat_cls, grid)
    if not combos:
        raise V.ValidationError("La rejilla no produjo combinaciones válidas.")
    for st in combos:
        st.prepare(series)
    dates, bounds = _date_bounds(series)
    folds, segments, fold_vars = [], [], []
    k = 0
    min_tail = max(1, test_days // 4)
    while k + train_days + min_tail <= len(dates):          # la última ventana puede ser parcial
        last = min(k + train_days + test_days, len(dates)) - 1
        tr0, tr1 = bounds[dates[k]][0], bounds[dates[k + train_days - 1]][1]
        te0, te1 = bounds[dates[k + train_days]][0], bounds[dates[last]][1]
        best, best_score, srs = None, -math.inf, []
        for st in combos:
            res = E.run(series, st, ecfg, tr0, tr1)
            sr = M.sharpe(M.daily_returns(res.equity, res.initial_equity))
            srs.append(sr)
            if len(res.trades) >= min_train_trades and sr > best_score:
                best, best_score = st, sr
        if len(srs) > 1:
            fold_vars.append(statistics.pvariance(srs))
        segments.append((te0, te1, best))
        folds.append({"train": [str(dates[k]), str(dates[k + train_days - 1])],
                      "test": [str(dates[k + train_days]), str(dates[last])],
                      "params": best.params if best else None,
                      "train_sharpe_annual": round(best_score * math.sqrt(252), 3) if best else None})
        k += test_days
    if not segments:
        return {"folds": [], "trades": [], "equity": [], "stress_trades": [], "n_trials": len(combos),
                "var_trial_sr": 0.0, "initial_equity": ecfg.initial_equity, "oos_start": None}
    a, b = segments[0][0], segments[-1][1]
    wf = _WalkForwardStrategy(segments, series.intraday)
    res = E.run(series, wf, ecfg, a, b)
    wf2 = _WalkForwardStrategy(segments, series.intraday)
    stress = E.run(series, wf2, ecfg.stressed(2.0), a, b)
    for f in folds:
        ft = [t for t in res.trades if f["test"][0] <= t["entry_date"] <= f["test"][1]]
        f["test_trades"] = len(ft)
        f["test_r"] = round(sum(t["r"] for t in ft), 3)
    return {"folds": folds, "trades": res.trades, "equity": res.equity, "stress_trades": stress.trades,
            "n_trials": len(combos), "var_trial_sr": statistics.fmean(fold_vars) if fold_vars else 0.0,
            "initial_equity": ecfg.initial_equity, "oos_start": a}


def block_bootstrap(rs, n_sims=5000, block=None, seed=19):
    """Remuestrea la secuencia de R por bloques (conserva rachas) -> drawdown y resultado final."""
    n = len(rs)
    if n < 2:
        return {}
    block = block or max(2, int(round(math.sqrt(n))))
    rng = random.Random(seed)
    finals, dds = [], []
    for _ in range(n_sims):
        path = []
        while len(path) < n:
            s = rng.randrange(n)
            path += [rs[(s + j) % n] for j in range(block)]
        eq = peak = mdd = 0.0
        for r in path[:n]:
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        finals.append(eq)
        dds.append(mdd)
    finals.sort()
    dds.sort()

    def q(xs, p):
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    return {"sims": n_sims, "block": block,
            "prob_loss_pct": round(100.0 * sum(1 for f in finals if f < 0) / n_sims, 1),
            "final_r_p5": round(q(finals, 0.05), 2), "final_r_p50": round(q(finals, 0.5), 2),
            "max_dd_r_p50": round(q(dds, 0.5), 2), "max_dd_r_p95": round(q(dds, 0.95), 2)}


def verdict(oos_stats, stress_stats, dsr_value, mc, risk_pct, criteria, oos_equity=None, bh=None):
    checks = []

    def add(name, value, rule, ok):
        checks.append({"check": name, "value": value, "rule": rule, "pass": bool(ok)})

    n = oos_stats.get("trades", 0)
    add("Operaciones fuera de muestra", n, ">= %d" % criteria["min_oos_trades"], n >= criteria["min_oos_trades"])
    ci = oos_stats.get("expectancy_r_ci95", [0, 0])
    add("Expectativa R (IC 95 %, extremo bajo)", ci[0], "> 0", n > 0 and ci[0] > 0)
    pf = oos_stats.get("profit_factor", 0)
    add("Profit factor neto de costos", pf, ">= %s" % criteria["min_profit_factor"],
        n > 0 and pf >= criteria["min_profit_factor"])
    add("Deflated Sharpe Ratio", round(dsr_value, 3), ">= %s" % criteria["min_dsr"], dsr_value >= criteria["min_dsr"])
    se = stress_stats.get("expectancy_r", 0)
    add("Expectativa R con costos x2", se, "> 0", stress_stats.get("trades", 0) > 0 and se > 0)
    dd = round(mc.get("max_dd_r_p95", math.inf) * risk_pct, 2) if mc else None
    add("Drawdown p95 Monte Carlo (% aprox.)", dd, "<= %s" % criteria["max_dd_p95_pct"],
        dd is not None and dd <= criteria["max_dd_p95_pct"])
    if criteria.get("require_beat_buy_hold", True) and bh:
        mine, theirs = (oos_equity or {}).get("sharpe_annual", 0), bh.get("sharpe_annual", 0)
        add("Sharpe vs comprar y mantener", "%s vs %s" % (mine, theirs), "mayor", mine > theirs)
    ok = all(c["pass"] for c in checks)
    return {"pass": ok,
            "label": "APROBADA para prueba en papel" if ok else "RECHAZADA",
            "meaning": ("Pasó todos los filtros fuera de muestra. Siguiente paso: operarla en PAPEL varias semanas "
                        "y comparar con el backtest antes de arriesgar dinero real." if ok else
                        "No hay evidencia suficiente de ventaja real después de costos. No la operes con dinero."),
            "checks": checks}


def bounds_end(series, last_date):
    end = 0
    for i, d in enumerate(series.dates):
        if str(d) <= last_date:
            end = i + 1
    return end


def evaluate(series, strat_cls, grid, ecfg, criteria, train_days=None, test_days=None, extra_trials=0):
    if train_days is None:
        train_days, test_days = (40, 10) if series.intraday else (756, 126)
    if test_days is None:
        test_days = 10 if series.intraday else 126
    wf = walk_forward(series, strat_cls, grid, ecfg, train_days, test_days)
    if not wf["folds"]:
        raise V.ValidationError("Datos insuficientes: hay %d sesiones y se necesitan al menos %d "
                                "(entrenamiento + prueba)." % (len(series.unique_dates()), train_days + test_days))
    oos = M.trade_stats(wf["trades"])
    stress = M.trade_stats(wf["stress_trades"])
    rets = M.daily_returns(wf["equity"], wf["initial_equity"])
    dsr_value = M.dsr(rets, wf["n_trials"] + int(extra_trials), wf["var_trial_sr"])
    mc = block_bootstrap([t["r"] for t in wf["trades"]])
    oos_eq = M.equity_stats(wf["equity"], wf["initial_equity"])
    bh = M.buy_and_hold(series, wf["oos_start"], bounds_end(series, wf["folds"][-1]["test"][1]))
    return {
        "symbol": series.symbol, "interval": series.interval, "strategy": strat_cls.name,
        "data": {"first": str(series.dates[0]), "last": str(series.dates[-1]),
                 "sessions": len(series.unique_dates()), "bars": len(series),
                 "fingerprint": series.fingerprint()},
        "setup": {"train_days": train_days, "test_days": test_days, "combos_tested": wf["n_trials"],
                  "trials_counted_for_dsr": wf["n_trials"] + int(extra_trials),
                  "risk_pct": ecfg.risk_pct, "costs": vars(ecfg.costs)},
        "out_of_sample": {"trades": oos, "equity": oos_eq, "dsr": round(dsr_value, 4)},
        "stress_costs_x2": stress,
        "monte_carlo": mc,
        "oos_monthly_returns": [round(x, 6) for x in monthly_returns(wf["equity"])] if not series.intraday else [],
        "buy_and_hold_same_period": bh,
        "folds": wf["folds"],
        "verdict": verdict(oos, stress, dsr_value, mc, ecfg.risk_pct, criteria, oos_eq, bh),
    }
