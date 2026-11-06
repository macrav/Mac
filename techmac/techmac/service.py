"""Operaciones de alto nivel compartidas por la CLI y el conector MCP (sin red)."""

import json

from . import config as C
from . import engine as E
from . import metrics as M
from . import strategies as S
from . import validate as V
from . import validation as W
from .ledger import Ledger
from .store import Store

IN_SAMPLE_WARNING = ("BACKTEST EN MUESTRA: parámetros elegidos a mano sobre los mismos datos. Sirve para explorar, "
                     "NO para decidir. Para decidir usa 'evaluate' (walk-forward fuera de muestra).")


def _series(h, symbol, interval, start=None, end=None):
    st = Store(h)
    try:
        s = st.load(V.symbol(symbol), V.interval(interval),
                    V.date(start, "start") if start else None, V.date(end, "end") if end else None)
    finally:
        st.close()
    if len(s) < 50:
        raise V.ValidationError("Solo hay %d velas de %s %s en tu almacén local. Importa o descarga más datos "
                                "(tm.py fetch / tm.py import-csv)." % (len(s), symbol, interval))
    return s


def data_status(h=None, symbol=None):
    st = Store(h)
    try:
        return st.inventory(symbol)
    finally:
        st.close()


def list_strategies():
    return [cls.describe() for cls in S.REGISTRY.values()]


def backtest(h=None, symbol=None, interval="1d", strategy="sma_cross", params=None, start=None, end=None,
             include_trades=20):
    cfg = C.load(h)
    s = _series(h, symbol, interval, start, end)
    strat = S.get(strategy)(**(params or {}))
    ecfg = E.EngineConfig.from_config(cfg)
    res = E.run(s, strat, ecfg)
    return {
        "warning": IN_SAMPLE_WARNING,
        "symbol": s.symbol, "interval": interval, "strategy": strategy, "params": strat.params,
        "period": [str(s.dates[0]), str(s.dates[-1])],
        "trades": M.trade_stats(res.trades),
        "equity": M.equity_stats(res.equity, res.initial_equity),
        "buy_and_hold": M.buy_and_hold(s),
        "signals": res.signals, "skipped": res.skipped,
        "last_trades": res.trades[-int(include_trades):] if include_trades else [],
    }


def evaluate(h=None, symbol=None, interval="1d", strategy="sma_cross", grid=None, train_days=None,
             test_days=None, start=None, end=None, actor="claude"):
    cfg = C.load(h)
    s = _series(h, symbol, interval, start, end)
    cls = S.get(strategy)
    ecfg = E.EngineConfig.from_config(cfg)
    report = W.evaluate(s, cls, grid, ecfg, cfg["criteria"], train_days, test_days)
    led = Ledger(h, cfg)
    try:
        report["evaluation_id"] = led.save_evaluation(report, actor)
    finally:
        led.close()
    return report


def summarize_evaluation(r):
    """Versión compacta para el chat."""
    oos = r["out_of_sample"]
    return {
        "evaluation_id": r.get("evaluation_id"), "symbol": r["symbol"], "interval": r["interval"],
        "strategy": r["strategy"], "data": {k: r["data"][k] for k in ("first", "last", "sessions")},
        "setup": r["setup"], "verdict": r["verdict"],
        "out_of_sample": {"trades": oos["trades"], "equity": oos["equity"], "dsr": oos["dsr"]},
        "stress_costs_x2": {k: r["stress_costs_x2"].get(k) for k in ("trades", "expectancy_r", "profit_factor")},
        "monte_carlo": r["monte_carlo"], "buy_and_hold_same_period": r["buy_and_hold_same_period"],
        "folds": len(r["folds"]),
        "params_per_fold": [f.get("params") for f in r["folds"]][-5:],
    }


def get_evaluation(h, eid):
    led = Ledger(h)
    try:
        e = led.evaluation(int(V.number(eid, "evaluation_id", 1, 1e12, True)))
    finally:
        led.close()
    if e is None:
        raise V.ValidationError("No existe la evaluación #%s." % eid)
    return json.loads(e["report"])


def import_plan_orders(h, path, evaluation_id=None, actor="humano-terminal"):
    """Importa propuestas desde trader/orders.json de day-trader-skill (solo compras con stop)."""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    out = []
    led = Ledger(h)
    try:
        for o in (doc.get("orders") or [])[:20]:
            if o.get("side") != "buy":
                out.append({"skipped": "solo compras", "symbol": o.get("symbol")})
                continue
            plan = o.get("plan") or {}
            try:
                out.append(led.propose(o.get("symbol"), int(o.get("qty")), plan.get("entry"),
                                       float(o.get("stop_loss_stop_price") or plan.get("stop")),
                                       float(o["take_profit_limit_price"]) if o.get("take_profit_limit_price") else None,
                                       evaluation_id, "importada de day-trader-skill: " + str(o.get("why", ""))[:300],
                                       actor))
            except Exception as e:  # noqa: BLE001 - se informa por orden
                out.append({"blocked": str(e), "symbol": o.get("symbol")})
    finally:
        led.close()
    return out


# ---------- portafolios, ranking y meta ----------

def list_allocations():
    from . import portfolio as P
    return [c.describe() for c in P.ALLOCATIONS.values()]


def evaluate_portfolio(h=None, symbols=None, strategy="dual_momentum", safe=None, benchmark=None, grid=None,
                       train_years=5, test_years=1, target_vol=0.0, max_leverage=1.0, start=None, end=None,
                       extra_trials=0, actor="claude"):
    from . import portfolio as P
    cfg = C.load(h)
    panel = P.load_panel(h, symbols, start, end)
    pcfg = P.PortfolioConfig.from_config(cfg, target_vol, max_leverage)
    report = P.evaluate(panel, P.get(strategy), grid, safe, pcfg, cfg["criteria"], train_years, test_years,
                        benchmark, extra_trials)
    led = Ledger(h, cfg)
    try:
        report["evaluation_id"] = led.save_evaluation(report, actor)
    finally:
        led.close()
    return report


def summarize_portfolio(r):
    return {k: r[k] for k in ("evaluation_id", "symbol", "strategy", "setup", "verdict", "out_of_sample",
                              "stress_costs_x2", "benchmark_buy_and_hold", "equal_weight_same_assets",
                              "current_target_weights") if k in r} | {"folds": len(r["folds"])}


def ranking(h=None, symbols=None, strategies=None, actor="claude"):
    """Evalúa cada estrategia diaria en cada símbolo. El DSR de cada una cuenta TODAS las combinaciones del
    ranking, porque elegir la mejor de muchas también es sobreajuste."""
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 20:
        raise V.ValidationError("Da de 1 a 20 símbolos.")
    names = strategies or [n for n, c in S.REGISTRY.items() if not c.intraday]
    classes = [S.get(n) for n in names]
    if any(c.intraday for c in classes):
        raise V.ValidationError("El ranking usa estrategias diarias.")
    total = sum(len(S.expand_grid(c)) for c in classes) * len(symbols)
    rows = []
    for sym in symbols:
        for c in classes:
            n_own = len(S.expand_grid(c))
            try:
                cfg = C.load(h)
                s = _series(h, sym, "1d")
                rep = W.evaluate(s, c, None, E.EngineConfig.from_config(cfg), cfg["criteria"],
                                 extra_trials=total - n_own)
                led = Ledger(h, cfg)
                try:
                    eid = led.save_evaluation(rep, actor)
                finally:
                    led.close()
                t, eq = rep["out_of_sample"]["trades"], rep["out_of_sample"]["equity"]
                rows.append({"symbol": sym, "strategy": c.name, "evaluation_id": eid,
                             "verdict": rep["verdict"]["label"], "trades": t.get("trades", 0),
                             "expectancy_r": t.get("expectancy_r"), "sharpe": eq.get("sharpe_annual"),
                             "buy_hold_sharpe": rep["buy_and_hold_same_period"].get("sharpe_annual"),
                             "cagr_pct": eq.get("cagr_pct"), "max_dd_pct": eq.get("max_drawdown_pct"),
                             "dsr": rep["out_of_sample"]["dsr"],
                             "failed": [x["check"] for x in rep["verdict"]["checks"] if not x["pass"]]})
            except V.ValidationError as e:
                rows.append({"symbol": sym, "strategy": c.name, "error": str(e)})
    rows.sort(key=lambda r: (r.get("dsr") is None, -(r.get("dsr") or 0)))
    return {"total_trials_counted": total, "rows": rows}


def goal(h=None, evaluation_id=None, symbol=None, capital=10000, monthly_contribution=0, target=1_000_000,
         max_years=40, leverages=(1, 1.5, 2, 3)):
    from . import goal as G
    from .portfolio import monthly_returns
    if evaluation_id is not None:
        rep = get_evaluation(h, evaluation_id)
        monthly = rep.get("oos_monthly_returns") or []
        source = "evaluación #%s (%s %s, fuera de muestra, %s)" % (evaluation_id, rep["symbol"], rep["strategy"],
                                                                    rep["verdict"]["label"])
    elif symbol:
        s = _series(h, symbol, "1d")
        monthly = monthly_returns([(d, b.c) for d, b in zip(s.dates, s.bars)])
        source = "comprar y mantener %s (%s a %s)" % (s.symbol, s.dates[0], s.dates[-1])
    else:
        raise V.ValidationError("Indica evaluation_id o symbol.")
    r = G.simulate(monthly, capital, monthly_contribution, target, max_years, list(leverages))
    r["source"] = source
    return r
