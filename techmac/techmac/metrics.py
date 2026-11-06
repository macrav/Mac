"""Métricas, intervalos de confianza y Deflated Sharpe Ratio."""

import math
import random
import statistics
from statistics import NormalDist

N = NormalDist()
EULER = 0.5772156649015329


def daily_returns(equity, initial):
    rets, prev = [], initial
    for _d, v in equity:
        rets.append(v / prev - 1.0 if prev > 0 else 0.0)
        prev = v
    return rets


def max_drawdown(values):
    peak, mdd = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def sharpe(rets):
    """Sharpe por período (sin anualizar)."""
    if len(rets) < 2:
        return 0.0
    sd = statistics.pstdev(rets)
    return statistics.fmean(rets) / sd if sd > 0 else 0.0


def sortino(rets):
    if len(rets) < 2:
        return 0.0
    down = [min(0.0, r) for r in rets]
    dd = math.sqrt(sum(x * x for x in down) / len(down))
    return statistics.fmean(rets) / dd if dd > 0 else 0.0


def skew_kurt(xs):
    n = len(xs)
    if n < 3:
        return 0.0, 3.0
    m = statistics.fmean(xs)
    sd = statistics.pstdev(xs)
    if sd == 0:
        return 0.0, 3.0
    sk = sum(((x - m) / sd) ** 3 for x in xs) / n
    ku = sum(((x - m) / sd) ** 4 for x in xs) / n
    return sk, ku


def psr(sr, n, skew, kurt, sr0=0.0):
    """Probabilistic Sharpe Ratio (Bailey y López de Prado, 2012)."""
    if n < 3:
        return 0.0
    den = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if den <= 0:
        return 0.0
    return N.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(den))


def expected_max_sr(var_sr, n_trials):
    """Sharpe máximo esperado por pura suerte tras probar n_trials combinaciones."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER) * N.inv_cdf(1 - 1.0 / n_trials)
                                + EULER * N.inv_cdf(1 - 1.0 / (n_trials * math.e)))


def dsr(rets, n_trials, var_trial_sr):
    """Deflated Sharpe Ratio: probabilidad de que el Sharpe real sea > 0 descontando el sobreajuste."""
    sr = sharpe(rets)
    sk, ku = skew_kurt(rets)
    return psr(sr, len(rets), sk, ku, expected_max_sr(var_trial_sr, n_trials))


def bootstrap_mean_ci(xs, n=2000, seed=19, alpha=0.05):
    if not xs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    k = len(xs)
    means = sorted(sum(xs[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return (means[int(alpha / 2 * n)], means[int((1 - alpha / 2) * n) - 1])


def trade_stats(trades):
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    rs = [t["r"] for t in trades]
    pnl = [t["pnl"] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    gl = -sum(losses)
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    lo, hi = bootstrap_mean_ci(rs)
    return {
        "trades": n,
        "win_rate_pct": round(100.0 * len(wins) / n, 1),
        "expectancy_r": round(statistics.fmean(rs), 4),
        "expectancy_r_ci95": [round(lo, 4), round(hi, 4)],
        "median_r": round(statistics.median(rs), 4),
        "profit_factor": round(sum(wins) / gl, 3) if gl > 0 else (999.0 if wins else 0.0),
        "total_pnl": round(sum(pnl), 2),
        "avg_win": round(statistics.fmean(wins), 2) if wins else 0.0,
        "avg_loss": round(statistics.fmean(losses), 2) if losses else 0.0,
        "exits": reasons,
    }


def equity_stats(equity, initial):
    if not equity:
        return {}
    rets = daily_returns(equity, initial)
    vals = [v for _d, v in equity]
    days = len(rets)
    total = vals[-1] / initial - 1.0
    years = days / 252.0
    cagr = (vals[-1] / initial) ** (1 / years) - 1 if years > 0 and vals[-1] > 0 else 0.0
    return {
        "days": days,
        "total_return_pct": round(100 * total, 2),
        "cagr_pct": round(100 * cagr, 2),
        "sharpe_annual": round(sharpe(rets) * math.sqrt(252), 3),
        "sortino_annual": round(sortino(rets) * math.sqrt(252), 3),
        "max_drawdown_pct": round(100 * max_drawdown([initial] + vals), 2),
    }


def buy_and_hold(series, start=0, end=None):
    end = len(series) if end is None else end
    if end - start < 2:
        return {}
    closes, by_day = series.bars, {}
    for i in range(start, end):
        by_day[series.dates[i]] = closes[i].c
    first = closes[start].o
    eq = [(d, c / first) for d, c in by_day.items()]
    return equity_stats(eq, 1.0)
