"""Motor de backtest por eventos, conservador a propósito.

Reglas de ejecución:
- La señal se calcula al CIERRE de la vela i; la orden se ejecuta en la APERTURA de i+1.
- Si la apertura ya está en o por debajo del stop (gap), la entrada se cancela.
- Stop: si la apertura abre por debajo del stop, se sale a la apertura (peor precio).
  Si dentro de la vela se tocan stop y objetivo a la vez, cuenta el STOP (pesimista).
- Objetivo (orden límite): solo se llena si el máximo lo SUPERA, no si apenas lo toca.
- Costos: comisión por acción con mínimo, slippage y medio spread en cada lado.
- Sin margen: no se compra más de lo que hay en efectivo.
- Intradía: cierre obligatorio en flat_by y nunca se duerme con posición.
"""

import math
from dataclasses import dataclass, field


@dataclass
class Costs:
    commission_per_share: float = 0.005
    commission_min: float = 1.0
    slippage_bps: float = 5.0
    spread_bps: float = 2.0

    @classmethod
    def from_config(cls, d):
        return cls(**d)


@dataclass
class EngineConfig:
    initial_equity: float = 10000.0
    risk_pct: float = 0.5
    max_position_pct: float = 100.0
    flat_by: int = 955
    costs: Costs = field(default_factory=Costs)
    cost_mult: float = 1.0

    @classmethod
    def from_config(cls, cfg):
        b = cfg["backtest"]
        h, m = b["flat_by"].split(":")
        return cls(initial_equity=b["initial_equity"], risk_pct=b["risk_pct"],
                   max_position_pct=b["max_position_pct"], flat_by=int(h) * 60 + int(m),
                   costs=Costs.from_config(cfg["costs"]))

    def stressed(self, mult):
        return EngineConfig(self.initial_equity, self.risk_pct, self.max_position_pct, self.flat_by,
                            self.costs, mult)


@dataclass
class Position:
    i_entry: int
    qty: int
    entry: float
    stop: float
    initial_stop: float
    target: object
    fee_in: float
    exit_next_open: bool = False
    exit_reason: str = ""


@dataclass
class Result:
    trades: list
    equity: list          # [(fecha, capital al cierre del día)]
    initial_equity: float
    signals: int = 0
    skipped: dict = field(default_factory=dict)


def _px(price, side, cfg):
    """side +1 compra, -1 venta: siempre en tu contra."""
    adj = price * (cfg.costs.slippage_bps + cfg.costs.spread_bps / 2.0) / 1e4 * cfg.cost_mult
    return price + adj if side > 0 else price - adj


def _fee(qty, cfg):
    if qty <= 0:
        return 0.0
    return max(cfg.costs.commission_min, cfg.costs.commission_per_share * qty) * cfg.cost_mult


def run(series, strategy, cfg, start=0, end=None):
    strategy.prepare(series)
    bars, n = series.bars, len(series.bars)
    end = n if end is None else min(end, n)
    step_min = series.step // 60
    cash = cfg.initial_equity
    pos = pending = None
    trades, equity = [], []
    signals = 0
    skipped = {"gap_through_stop": 0, "too_small": 0, "no_cash": 0}

    for i in range(start, end):
        b = bars[i]
        d = series.dates[i]
        last_of_day = series.intraday and (i + 1 >= n or series.dates[i + 1] != d)

        # 1) ejecutar la entrada pendiente en la apertura
        if pending is not None:
            sig_i, qty, stop, tgt = pending
            pending = None
            same_day = not series.intraday or series.dates[sig_i] == d
            if not same_day:
                pass
            elif b.o <= stop or (tgt is not None and b.o >= tgt):
                skipped["gap_through_stop"] += 1
            else:
                fill = _px(b.o, +1, cfg)
                fee = _fee(qty, cfg)
                if qty * fill + fee > cash:
                    qty = int((cash - _fee(qty, cfg)) // fill)
                if qty < 1:
                    skipped["no_cash"] += 1
                else:
                    fee = _fee(qty, cfg)
                    cash -= qty * fill + fee
                    pos = Position(i, qty, fill, stop, stop, tgt, fee)

        # 2) gestionar la posición abierta
        if pos is not None:
            exit_px = reason = None
            if pos.i_entry != i:
                if pos.exit_next_open:
                    exit_px, reason = _px(b.o, -1, cfg), pos.exit_reason
                elif b.o <= pos.stop:
                    exit_px, reason = _px(b.o, -1, cfg), "stop_gap"
                elif pos.target is not None and b.o > pos.target:
                    exit_px, reason = b.o, "target_gap"
            if exit_px is None:
                if b.l <= pos.stop:
                    exit_px, reason = _px(pos.stop, -1, cfg), "stop"
                elif pos.target is not None and b.h > pos.target:
                    exit_px, reason = pos.target, "target"
            if exit_px is None and series.intraday and (series.minutes[i] + step_min >= cfg.flat_by or last_of_day):
                exit_px, reason = _px(b.c, -1, cfg), "flat_by"
            if exit_px is None and i == end - 1:
                exit_px, reason = _px(b.c, -1, cfg), "end_of_test"
            if exit_px is not None:
                fee_out = _fee(pos.qty, cfg)
                cash += pos.qty * exit_px - fee_out
                pnl = pos.qty * (exit_px - pos.entry) - pos.fee_in - fee_out
                risk = pos.qty * (pos.entry - pos.initial_stop)
                trades.append({
                    "entry_ts": bars[pos.i_entry].ts, "exit_ts": b.ts,
                    "entry_date": str(series.dates[pos.i_entry]), "exit_date": str(d),
                    "qty": pos.qty, "entry": round(pos.entry, 4), "exit": round(exit_px, 4),
                    "stop": round(pos.initial_stop, 4),
                    "target": None if pos.target is None else round(pos.target, 4),
                    "reason": reason, "pnl": round(pnl, 2), "risk_usd": round(risk, 2),
                    "r": round(pnl / risk, 4) if risk > 0 else 0.0, "bars": i - pos.i_entry + 1,
                })
                pos = None
            else:
                new_stop = strategy.trail(i, pos)
                if new_stop is not None and new_stop > pos.stop:
                    pos.stop = new_stop
                if strategy.exit(i, pos):
                    pos.exit_next_open, pos.exit_reason = True, "signal"

        # 3) buscar nueva señal al cierre (se ejecuta en la siguiente apertura)
        if pos is None and pending is None and i < end - 1 and not last_of_day:
            sig = strategy.entry(i)
            if sig is not None:
                signals += 1
                stop, tgt = sig
                per_share = b.c - stop
                if per_share > 0:
                    eq = cash
                    qty = math.floor(eq * cfg.risk_pct / 100.0 / per_share)
                    cap = math.floor(eq * cfg.max_position_pct / 100.0 / (b.c * 1.01))
                    qty = min(qty, cap)
                    if qty >= 1:
                        pending = (i, qty, stop, tgt)
                    else:
                        skipped["too_small"] += 1

        mark = cash + (pos.qty * b.c if pos is not None else 0.0)
        if equity and equity[-1][0] == d:
            equity[-1] = (d, mark)
        else:
            equity.append((d, mark))

    return Result(trades, equity, cfg.initial_equity, signals, skipped)
