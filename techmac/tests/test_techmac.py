"""Tests offline de TechMaC.  Ejecutar: cd techmac && python3 -m unittest -v"""

import datetime as dt
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from techmac import config as C  # noqa: E402
from techmac import engine as E  # noqa: E402
from techmac import metrics as M  # noqa: E402
from techmac import strategies as S  # noqa: E402
from techmac import validate as V  # noqa: E402
from techmac import validation as W  # noqa: E402
from techmac.ledger import Ledger, RiskBlocked, confirmation_phrase  # noqa: E402
from techmac.store import Bar, Series, Store, parse_csv  # noqa: E402
from techmac.timeutil import ny_to_epoch, to_ny  # noqa: E402

NO_COSTS = E.Costs(0.0, 0.0, 0.0, 0.0)


def daily_series(n=1500, seed=1, drift=0.0004, vol=0.012, symbol="TEST"):
    rng = random.Random(seed)
    bars, px = [], 100.0
    day = dt.date(2015, 1, 2)
    while len(bars) < n:
        if day.weekday() < 5:
            o = px * (1 + rng.gauss(0, vol / 4))
            c = o * (1 + rng.gauss(drift, vol))
            h = max(o, c) * (1 + abs(rng.gauss(0, vol / 3)))
            l = min(o, c) * (1 - abs(rng.gauss(0, vol / 3)))
            ts = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
            bars.append(Bar(ts, o, h, l, c, 1e6))
            px = c
        day += dt.timedelta(days=1)
    return Series(symbol, "1d", bars)


def intraday_series(days=80, seed=2, symbol="TEST"):
    rng = random.Random(seed)
    bars, px = [], 50.0
    day = dt.date(2026, 6, 1)
    count = 0
    while count < days:
        if day.weekday() < 5:
            count += 1
            for k in range(78):
                t = ny_to_epoch(dt.datetime(day.year, day.month, day.day, 9, 30) + dt.timedelta(minutes=5 * k))
                o = px
                c = o * (1 + rng.gauss(0, 0.002))
                h = max(o, c) * (1 + abs(rng.gauss(0, 0.001)))
                l = min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
                bars.append(Bar(t, o, h, l, c, 1000))
                px = c
        day += dt.timedelta(days=1)
    return Series(symbol, "5m", bars)


class FixedSignal(S.Strategy):
    """Estrategia de prueba: señal en índices dados."""
    name = "fixed"
    intraday = False

    def __init__(self, signals, intraday=False):
        super().__init__()
        self.signals, self.intraday = signals, intraday

    def _prepare(self, s):
        self._sig = [self.signals.get(i) for i in range(len(s))]


def mk(rows, interval="1d"):
    """rows: [(o,h,l,c)] en días hábiles consecutivos."""
    bars, day = [], dt.date(2024, 1, 1)
    for r in rows:
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        ts = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
        bars.append(Bar(ts, *r, 1000))
        day += dt.timedelta(days=1)
    return Series("X", interval, bars)


class TestTime(unittest.TestCase):
    def test_dst(self):
        summer = ny_to_epoch(dt.datetime(2026, 7, 1, 9, 30))
        winter = ny_to_epoch(dt.datetime(2026, 1, 5, 9, 30))
        self.assertEqual(dt.datetime.fromtimestamp(summer, dt.timezone.utc).hour, 13)
        self.assertEqual(dt.datetime.fromtimestamp(winter, dt.timezone.utc).hour, 14)
        self.assertEqual(to_ny(summer), dt.datetime(2026, 7, 1, 9, 30))
        # cambio de horario: 8 de marzo de 2026
        self.assertEqual(to_ny(ny_to_epoch(dt.datetime(2026, 3, 9, 9, 30))).hour, 9)


class TestValidation(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(V.symbol(" brk-b "), "BRK-B")
        for bad in ["../etc", "A B", "", "x" * 20, "AAPL;rm", 5]:
            with self.assertRaises(V.ValidationError):
                V.symbol(bad)

    def test_numbers(self):
        for bad in [float("nan"), float("inf"), True, "abc", None]:
            with self.assertRaises(V.ValidationError):
                V.number(bad, "x")
        with self.assertRaises(V.ValidationError):
            V.number(1.5, "x", integer=True)

    def test_config_rejects_unknown_and_out_of_range(self):
        with tempfile.TemporaryDirectory() as d:
            C.init(d)
            p = Path(d) / "config.json"
            cfg = json.loads(p.read_text())
            cfg["max_loss_per_trade_usd"] = -5
            p.write_text(json.dumps(cfg))
            with self.assertRaises(V.ValidationError):
                C.load(d)
            cfg["max_loss_per_trade_usd"] = 50
            cfg["broker"] = "alpaca"
            p.write_text(json.dumps(cfg))
            with self.assertRaises(V.ValidationError):
                C.load(d)

    def test_home_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            home, _ = C.init(Path(d) / "h")
            self.assertEqual(os.stat(home).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(home / "config.json").st_mode & 0o777, 0o600)


class TestStore(unittest.TestCase):
    def test_integrity_and_csv(self):
        raw = (b"Date,Open,High,Low,Close,Volume\n2024-01-02,10,11,9,10.5,100\n"
               b"2024-01-03,10,9,11,10,100\n2024-01-04,abc,1,1,1,1\n2024-01-05,-1,1,1,1,1\n")
        bars, bad = parse_csv(raw, "1d")
        self.assertEqual(bad, 1)
        with tempfile.TemporaryDirectory() as d:
            st = Store(d)
            good, rejected = st.upsert("X", "1d", bars, "csv", raw)
            self.assertEqual((good, rejected), (1, 2))
            self.assertEqual(os.stat(Path(d) / "bars.db").st_mode & 0o777, 0o600)
            st.close()

    def test_regular_session_filter(self):
        s = intraday_series(days=2)
        extra = Bar(ny_to_epoch(dt.datetime(2026, 6, 1, 8, 0)), 50, 51, 49, 50, 1)
        s2 = Series("X", "5m", [extra] + s.bars).regular_session()
        self.assertEqual(len(s2), len(s))


class TestEngine(unittest.TestCase):
    cfg = E.EngineConfig(10000, 1.0, 100.0, 955, NO_COSTS)

    def test_fills_next_open_not_signal_close(self):
        s = mk([(100, 101, 99, 100), (102, 103, 101, 102.5), (103, 104, 102, 103), (103, 104, 102, 103)])
        res = E.run(s, FixedSignal({0: (95.0, None)}), self.cfg)
        self.assertEqual(res.trades[0]["entry"], 102)   # apertura de la vela siguiente

    def test_gap_below_stop_fills_at_open(self):
        s = mk([(100, 101, 99, 100), (100, 101, 99.5, 100), (90, 91, 88, 89), (89, 90, 88, 89)])
        res = E.run(s, FixedSignal({0: (95.0, 110.0)}), self.cfg)
        t = res.trades[0]
        self.assertEqual((t["reason"], t["exit"]), ("stop_gap", 90))
        self.assertLess(t["r"], -1)  # el gap cuesta más que 1R

    def test_same_bar_stop_and_target_is_stop(self):
        s = mk([(100, 101, 99, 100), (100, 101, 99.5, 100), (100, 120, 80, 100), (100, 101, 99, 100)])
        res = E.run(s, FixedSignal({0: (95.0, 110.0)}), self.cfg)
        self.assertEqual(res.trades[0]["reason"], "stop")

    def test_target_needs_to_trade_through(self):
        s = mk([(100, 101, 99, 100), (100, 101, 99.5, 100), (100, 110, 99, 105), (105, 111, 104, 110)])
        res = E.run(s, FixedSignal({0: (95.0, 110.0)}), self.cfg)
        self.assertEqual(res.trades[0]["exit_date"], str(s.dates[3]))

    def test_entry_cancelled_when_open_gaps_below_stop(self):
        s = mk([(100, 101, 99, 100), (94, 95, 93, 94), (94, 95, 93, 94)])
        res = E.run(s, FixedSignal({0: (95.0, None)}), self.cfg)
        self.assertEqual(res.trades, [])
        self.assertEqual(res.skipped["gap_through_stop"], 1)

    def test_costs_reduce_pnl(self):
        s = daily_series(600)
        st = S.SmaCross(fast=10, slow=50)
        free = E.run(s, st, self.cfg)
        paid = E.run(s, st, E.EngineConfig(10000, 1.0, 100.0, 955, E.Costs()))
        self.assertGreater(len(free.trades), 3)
        self.assertLess(sum(t["pnl"] for t in paid.trades), sum(t["pnl"] for t in free.trades))

    def test_intraday_never_holds_overnight(self):
        s = intraday_series(days=30)
        res = E.run(s, S.OpeningRangeBreakout(target_r=0), E.EngineConfig(10000, 1.0, 100.0, 955, E.Costs()))
        self.assertGreater(len(res.trades), 5)
        for t in res.trades:
            self.assertEqual(t["entry_date"], t["exit_date"])
            self.assertLessEqual(to_ny(t["exit_ts"]).hour * 60 + to_ny(t["exit_ts"]).minute, 955)

    def test_no_margin(self):
        s = daily_series(400)
        cfg = E.EngineConfig(10000, 10.0, 100.0, 955, E.Costs())
        res = E.run(s, S.SmaCross(fast=10, slow=50, atr_mult=0.5), cfg)
        for d, eq in res.equity:
            self.assertGreater(eq, 0)
        for t in res.trades:
            self.assertLessEqual(t["qty"] * t["entry"], 10000 * 3)


class TestNoLookahead(unittest.TestCase):
    """Cambiar el futuro no puede cambiar señales del pasado."""

    def _check(self, strat_factory, series, cut):
        a = strat_factory()
        a.prepare(series)
        rng = random.Random(7)
        future = [Bar(b.ts, b.o * 2, b.h * 2.5, b.l * 1.5, b.c * rng.uniform(1.5, 2.5), b.v) for b in series.bars[cut:]]
        future = [Bar(b.ts, b.o, max(b.h, b.o, b.c), min(b.l, b.o, b.c), b.c, b.v) for b in future]
        altered = Series(series.symbol, series.interval, series.bars[:cut] + future)
        b = strat_factory()
        b.prepare(altered)
        self.assertEqual(a._sig[:cut], b._sig[:cut])

    def test_strategies(self):
        d = daily_series(800)
        self._check(lambda: S.SmaCross(fast=10, slow=50), d, 500)
        self._check(lambda: S.Donchian(entry_n=20, exit_n=10), d, 500)
        self._check(lambda: S.OpeningRangeBreakout(), intraday_series(10), 400)


class TestMetrics(unittest.TestCase):
    def test_drawdown(self):
        self.assertAlmostEqual(M.max_drawdown([100, 120, 90, 130]), 0.25)

    def test_dsr_penalizes_many_trials(self):
        rng = random.Random(3)
        rets = [rng.gauss(0.0008, 0.01) for _ in range(500)]
        one = M.dsr(rets, 1, 0.0)
        many = M.dsr(rets, 100, 0.002)
        self.assertLess(many, one)

    def test_bootstrap_ci_contains_mean(self):
        xs = [1, -1, 2, -1, 0.5, -0.5, 1.5, -1]
        lo, hi = M.bootstrap_mean_ci(xs)
        self.assertLess(lo, sum(xs) / len(xs))
        self.assertGreater(hi, sum(xs) / len(xs))


class TestWalkForward(unittest.TestCase):
    def test_random_walk_is_rejected(self):
        """Datos sin ventaja: el veredicto debe ser RECHAZADA."""
        s = daily_series(1500, seed=11, drift=0.0)
        cfg = C._defaults(C.DEFAULTS)
        ecfg = E.EngineConfig.from_config(cfg)
        r = W.evaluate(s, S.SmaCross, None, ecfg, cfg["criteria"], 504, 126)
        self.assertFalse(r["verdict"]["pass"])
        self.assertGreater(len(r["folds"]), 3)
        # las ventanas de prueba nunca se solapan con su entrenamiento
        for f in r["folds"]:
            self.assertLess(f["train"][1], f["test"][0])

    def test_real_edge_is_detected(self):
        """Serie con tendencias persistentes: un sistema de ruptura debe aprobar."""
        rng = random.Random(5)
        bars, px, day, drift = [], 100.0, dt.date(1990, 1, 2), 0.0
        while len(bars) < 6000:
            if day.weekday() < 5:
                if rng.random() < 0.01:
                    drift = rng.choice([0.004, -0.004])
                o = px
                c = o * (1 + rng.gauss(drift, 0.01))
                h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.003))), min(o, c) * (1 - abs(rng.gauss(0, 0.003)))
                bars.append(Bar(int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()),
                                o, h, l, c, 1))
                px = c
            day += dt.timedelta(days=1)
        cfg = C._defaults(C.DEFAULTS)
        cfg["criteria"]["min_oos_trades"] = 20
        r = W.evaluate(Series("T", "1d", bars), S.Donchian, None, E.EngineConfig.from_config(cfg), cfg["criteria"],
                       756, 126)
        self.assertTrue(r["verdict"]["pass"], r["verdict"]["checks"])

    def test_not_enough_data(self):
        s = daily_series(300)
        cfg = C._defaults(C.DEFAULTS)
        with self.assertRaises(V.ValidationError):
            W.evaluate(s, S.SmaCross, None, E.EngineConfig.from_config(cfg), cfg["criteria"])

    def test_grid_limits(self):
        with self.assertRaises(V.ValidationError):
            S.expand_grid(S.SmaCross, {"fast": list(range(2, 22)), "slow": list(range(30, 50)), "atr_n": [5]})
        with self.assertRaises(V.ValidationError):
            S.expand_grid(S.SmaCross, {"__class__": [1]})


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = self.tmp.name
        C.init(self.h)
        self.led = Ledger(self.h)
        rep = {"symbol": "SPY", "interval": "1d", "strategy": "sma_cross", "data": {"fingerprint": "x"},
               "verdict": {"pass": True, "label": "APROBADA para prueba en papel"}}
        self.ok_eval = self.led.save_evaluation(rep, "test")
        rep2 = dict(rep, verdict={"pass": False, "label": "RECHAZADA"})
        self.bad_eval = self.led.save_evaluation(rep2, "test")

    def tearDown(self):
        self.led.close()
        self.tmp.cleanup()

    def test_requires_passing_evaluation(self):
        with self.assertRaises(RiskBlocked):
            self.led.propose("SPY", 5, 500, 495, 510, None)
        with self.assertRaises(RiskBlocked):
            self.led.propose("SPY", 5, 500, 495, 510, self.bad_eval)
        with self.assertRaises(RiskBlocked) as cm:
            self.led.propose("AAPL", 5, 200, 195, 210, self.ok_eval)
        self.assertIn("es de SPY", " ".join(cm.exception.reasons))

    def test_risk_limits(self):
        with self.assertRaises(RiskBlocked):            # $100 de riesgo > $50
            self.led.propose("SPY", 20, 500, 495, 510, self.ok_eval)
        with self.assertRaises(RiskBlocked):            # beneficio/riesgo 0.4 < 1
            self.led.propose("SPY", 5, 500, 495, 502, self.ok_eval)
        with self.assertRaises(RiskBlocked):            # stop por encima
            self.led.propose("SPY", 5, 500, 505, 510, self.ok_eval)

    def test_approve_needs_exact_phrase_and_full_flow(self):
        o = self.led.propose("SPY", 5, 500, 495, 510, self.ok_eval)
        with self.assertRaises(RiskBlocked):
            self.led.approve(o["id"], "si")
        self.assertEqual(self.led.order(o["id"])["status"], "proposed")
        self.led.approve(o["id"], confirmation_phrase(o))
        self.led.record_fill(o["id"], 500.5)
        c = self.led.record_exit(o["id"], 510)
        self.assertEqual(c["pnl"], 47.5)
        st = self.led.status()
        self.assertEqual(st["closed_trades"], 1)
        self.assertTrue(self.led.verify_audit()["ok"])

    def test_portfolio_evaluation_covers_member_symbols(self):
        rep = {"symbol": "PORT:SPY,EFA,SHY", "interval": "1d", "strategy": "dual_momentum",
               "data": {"fingerprint": "x"}, "verdict": {"pass": True, "label": "APROBADA para prueba en papel"}}
        eid = self.led.save_evaluation(rep, "test")
        self.led.propose("EFA", 5, 80, 75, 90, eid)
        with self.assertRaises(RiskBlocked):
            self.led.propose("QQQ", 5, 80, 75, 90, eid)

    def test_kill_switch(self):
        (Path(self.h) / "KILL").write_text("x")
        with self.assertRaises(RiskBlocked) as cm:
            self.led.propose("SPY", 5, 500, 495, 510, self.ok_eval)
        self.assertIn("KILL", " ".join(cm.exception.reasons))

    def test_daily_loss_limit_counts_open_risk(self):
        for _ in range(2):
            o = self.led.propose("SPY", 9, 500, 495, 510, self.ok_eval)   # $45 de riesgo cada una
            self.led.approve(o["id"], confirmation_phrase(o))
        with self.assertRaises(RiskBlocked):       # 45+45+45+... con 3 aprobadas también choca con max trades
            o = self.led.propose("SPY", 9, 500, 495, 510, self.ok_eval)
            self.led.approve(o["id"], confirmation_phrase(o))
            self.led.propose("SPY", 9, 500, 495, 510, self.ok_eval)

    def test_audit_is_append_only_and_tamper_evident(self):
        self.led.propose("SPY", 5, 500, 495, 510, self.ok_eval)
        import sqlite3
        with self.assertRaises(sqlite3.DatabaseError):
            self.led.conn.execute("UPDATE audit SET payload='{}' WHERE id=1")
        with self.assertRaises(sqlite3.DatabaseError):
            self.led.conn.execute("DELETE FROM audit")
        # aunque alguien borre los triggers, la cadena de hashes lo delata
        self.led.conn.execute("DROP TRIGGER audit_no_update")
        self.led.conn.execute("UPDATE audit SET payload='{\"x\":1}' WHERE id=2")
        self.assertFalse(self.led.verify_audit()["ok"])


class TestNewStrategies(unittest.TestCase):
    def test_no_lookahead(self):
        d = daily_series(800)
        for cls in (S.Rsi2, S.Ibs, S.TrendFilter, S.TimeSeriesMomentum):
            TestNoLookahead._check(self, cls, d, 500)

    def test_they_trade(self):
        d = daily_series(1500, drift=0.0005)
        cfg = E.EngineConfig(10000, 1.0, 100.0, 955, E.Costs())
        for cls in (S.Rsi2, S.Ibs, S.TrendFilter, S.TimeSeriesMomentum):
            res = E.run(d, cls(), cfg)
            self.assertGreater(len(res.trades), 3, cls.name)

    def test_rsi_bounds(self):
        r = S.rsi([float(x % 7) + 1 for x in range(100)], 2)
        self.assertTrue(all(x is None or 0 <= x <= 100 for x in r))


def make_panel(n=2600, k=3, seed=4, jump=None):
    from techmac.portfolio import Panel
    rng = random.Random(seed)
    dates, d = [], dt.date(2000, 1, 3)
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += dt.timedelta(days=1)
    closes, px = [], [100.0] * k
    for t in range(n):
        px = [p * (1 + rng.gauss(0.0002, 0.01)) for p in px]
        if jump and t in jump:
            px[jump[t][0]] *= jump[t][1]
        closes.append(list(px))
    return Panel(["A", "B", "C"][:k], dates, closes)


class TestPortfolio(unittest.TestCase):
    def test_one_day_execution_lag(self):
        from techmac import portfolio as P
        base = make_panel(300, 2)
        t0 = next(t for t in range(30, 300) if base.month_end[t])
        flat = [[100.0, 100.0] for _ in range(300)]
        for t in range(t0 + 2, 300):
            flat[t][1] = 200.0                     # B se duplica el día t0+2
        p = P.Panel(["A", "B"], base.dates, flat)
        p2 = [[100.0, 100.0] for _ in range(300)]
        for t in range(t0 + 1, 300):
            p2[t][1] = 200.0                       # ... o el día t0+1, antes de poder ejecutar
        p2 = P.Panel(["A", "B"], base.dates, p2)
        cfg = P.PortfolioConfig(cost_bps=0)
        eq, _ = P.run(p, lambda t: P.EqualWeight(), None, cfg, t0, 300)
        eq2, _ = P.run(p2, lambda t: P.EqualWeight(), None, cfg, t0, 300)
        self.assertAlmostEqual(eq[-1][1], 15000.0, places=4)   # captura la mitad del salto
        self.assertAlmostEqual(eq2[-1][1], 10000.0, places=4)  # no puede capturar lo que pasó antes de ejecutar

    def test_costs_and_no_lookahead(self):
        from techmac import portfolio as P
        p = make_panel()
        a, _ = P.run(p, lambda t: P.DualMomentum(lookback=63), 2, P.PortfolioConfig(cost_bps=0), 300, 2600)
        b, _ = P.run(p, lambda t: P.DualMomentum(lookback=63), 2, P.PortfolioConfig(cost_bps=20), 300, 2600)
        self.assertLess(b[-1][1], a[-1][1])
        future = [row if t < 1500 else [x * random.Random(t).uniform(0.5, 2) for x in row]
                  for t, row in enumerate(p.closes)]
        q = P.Panel(p.symbols, p.dates, future)
        for cls in P.ALLOCATIONS.values():
            st = cls()
            for t in (400, 900, 1499):
                self.assertEqual(st.weights(p, t, 2), st.weights(q, t, 2), cls.name)

    def test_evaluate_random_is_rejected(self):
        from techmac import portfolio as P
        cfg = C._defaults(C.DEFAULTS)
        r = P.evaluate(make_panel(), P.DualMomentum, None, "C", P.PortfolioConfig.from_config(cfg),
                       cfg["criteria"], 3, 1)
        self.assertFalse(r["verdict"]["pass"])
        self.assertIn("current_target_weights", r)
        self.assertGreater(len(r["oos_monthly_returns"]), 36)
        for f in r["folds"]:
            self.assertLess(f["train"][1], f["test"][0])

    def test_safe_asset_required(self):
        from techmac import portfolio as P
        cfg = C._defaults(C.DEFAULTS)
        with self.assertRaises(V.ValidationError):
            P.evaluate(make_panel(), P.DualMomentum, None, None, P.PortfolioConfig.from_config(cfg), cfg["criteria"])


class TestGoal(unittest.TestCase):
    def test_leverage_raises_risk(self):
        from techmac import goal as G
        rng = random.Random(1)
        monthly = [rng.gauss(0.008, 0.045) for _ in range(360)]
        r = G.simulate(monthly, 10000, 500, 1_000_000, 40, [1, 3], sims=1500)
        one, three = r["results"]
        self.assertGreaterEqual(three["prob_ruin_pct"], one["prob_ruin_pct"])
        self.assertGreater(three["prob_drop_50pct"], one["prob_drop_50pct"])

    def test_contributions_only(self):
        from techmac import goal as G
        r = G.simulate([0.003] * 120, 0, 250, 1e9, 10, [1], sims=200)
        x = r["results"][0]
        self.assertEqual(x["prob_ruin_pct"], 0.0)
        self.assertGreater(x["final_median"], 250 * 120)          # aportes + rendimiento
        self.assertLess(x["final_median"], 250 * 120 * 1.3)

    def test_needs_history(self):
        from techmac import goal as G
        with self.assertRaises(V.ValidationError):
            G.simulate([0.01] * 10, 10000, 0, 1e6, 10, [1])


class TestMCP(unittest.TestCase):
    def _session(self, msgs, home):
        env = dict(os.environ, TECHMAC_HOME=home)
        p = subprocess.run([sys.executable, "-I", str(ROOT / "tm_mcp.py")], input="\n".join(json.dumps(m) for m in msgs),
                           capture_output=True, text=True, env=env, timeout=60)
        return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]

    def test_protocol_and_no_approve_tool(self):
        with tempfile.TemporaryDirectory() as h:
            out = self._session([
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "propose_order", "arguments": {"symbol": "SPY", "qty": 5, "entry": 500,
                                                                   "stop": 495, "target": 510, "evaluation_id": 1}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "approve_order", "arguments": {"id": 1}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                 "params": {"name": "data_status", "arguments": {"symbol": "../../etc"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                 "params": {"name": "backtest", "arguments": {"symbol": "SPY", "interval": "1d",
                                                              "strategy": "sma_cross", "evil": 1}}},
            ], h)
            by = {m["id"]: m for m in out}
            self.assertEqual(by[1]["result"]["serverInfo"]["name"], "TechMaC")
            names = {t["name"] for t in by[2]["result"]["tools"]}
            self.assertIn("evaluate", names)
            self.assertTrue({"evaluate_portfolio", "ranking", "goal_simulator"} <= names)
            self.assertFalse(any("approve" in n or "execute" in n or "fetch" in n for n in names))
            self.assertTrue(by[3]["result"]["isError"])           # sin evaluación aprobada
            self.assertTrue(by[4]["result"]["isError"])           # herramienta inexistente
            self.assertTrue(by[5]["result"]["isError"])           # símbolo malicioso
            self.assertTrue(by[6]["result"]["isError"])           # argumento extra

    def test_network_blocked_inside_server(self):
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from techmac import mcp_server\nmcp_server._block_network()\n"
                "import socket\n"
                "try:\n    socket.create_connection(('example.com', 443))\n    print('ABIERTA')\n"
                "except PermissionError:\n    print('BLOQUEADA')\n") % str(ROOT)
        p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=30)
        self.assertIn("BLOQUEADA", p.stdout)

    def test_cli_approve_refuses_without_tty(self):
        with tempfile.TemporaryDirectory() as h:
            env = dict(os.environ, TECHMAC_HOME=h)
            p = subprocess.run([sys.executable, "-I", str(ROOT / "tm.py"), "approve", "1"], capture_output=True,
                               text=True, env=env, stdin=subprocess.DEVNULL, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("terminal interactiva", p.stderr)


if __name__ == "__main__":
    unittest.main()
