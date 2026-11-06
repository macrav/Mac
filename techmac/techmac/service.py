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
