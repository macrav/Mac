"""Libro local de órdenes en papel con auditoría encadenada por hash.

TechMaC NO se conecta a ningún broker. Una orden aprobada es un ticket para que
TÚ la ejecutes a mano (o no). Después registras el precio real con record-fill
y record-exit, y TechMaC lleva tus límites de riesgo y tu historial.
"""

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

from . import config as C
from . import validate as V
from .timeutil import UTC, ny_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations(
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
  strategy TEXT NOT NULL, passed INTEGER NOT NULL, label TEXT NOT NULL, report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, ny_date TEXT NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK(side='buy'), qty INTEGER NOT NULL CHECK(qty>0),
  entry REAL NOT NULL, stop REAL NOT NULL, target REAL, risk_usd REAL NOT NULL,
  evaluation_id INTEGER, note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN ('proposed','approved','rejected','expired','open','closed','cancelled')),
  approved_at TEXT, fill_price REAL, fill_qty INTEGER, exit_price REAL, pnl REAL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  payload TEXT NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
  BEGIN SELECT RAISE(ABORT, 'la auditoria es de solo agregar'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'la auditoria es de solo agregar'); END;
"""

GENESIS = "0" * 64


class RiskBlocked(Exception):
    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _now():
    return dt.datetime.now(UTC).isoformat(timespec="seconds")


def _hash(prev, at, actor, action, payload):
    return hashlib.sha256("|".join((prev, at, actor, action, payload)).encode()).hexdigest()


def confirmation_phrase(order):
    return "APROBAR %d %s %d" % (order["id"], order["symbol"], order["qty"])


class Ledger:
    def __init__(self, h=None, cfg=None):
        self.home = C.secure_dir(h or C.home())
        self.cfg = cfg or C.load(self.home)
        self.path = Path(self.home) / "ledger.db"
        new = not self.path.exists()
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if new:
            C.secure_file(self.path)
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # ---------- auditoría ----------
    def _audit(self, actor, action, payload):
        row = self.conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = row["hash"] if row else GENESIS
        at = _now()
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        self.conn.execute("INSERT INTO audit(at,actor,action,payload,prev,hash) VALUES(?,?,?,?,?,?)",
                          (at, actor, action, body, prev, _hash(prev, at, actor, action, body)))

    def verify_audit(self):
        prev, n = GENESIS, 0
        for r in self.conn.execute("SELECT * FROM audit ORDER BY id"):
            if r["prev"] != prev or _hash(prev, r["at"], r["actor"], r["action"], r["payload"]) != r["hash"]:
                return {"ok": False, "entries": n, "broken_at_id": r["id"]}
            prev, n = r["hash"], n + 1
        return {"ok": True, "entries": n, "head": prev}

    def audit_tail(self, limit=20):
        rows = self.conn.execute("SELECT id,at,actor,action,payload FROM audit ORDER BY id DESC LIMIT ?",
                                 (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    # ---------- evaluaciones ----------
    def save_evaluation(self, report, actor):
        v = report["verdict"]
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self.conn.execute(
                "INSERT INTO evaluations(created,symbol,interval,strategy,passed,label,report) VALUES(?,?,?,?,?,?,?)",
                (_now(), report["symbol"], report["interval"], report["strategy"], int(v["pass"]), v["label"],
                 json.dumps(report, ensure_ascii=False, default=str)))
            eid = cur.lastrowid
            self._audit(actor, "evaluation_saved", {"id": eid, "symbol": report["symbol"],
                                                    "strategy": report["strategy"], "pass": v["pass"],
                                                    "data_fingerprint": report["data"]["fingerprint"]})
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return eid

    def evaluation(self, eid):
        r = self.conn.execute("SELECT * FROM evaluations WHERE id=?", (int(eid),)).fetchone()
        return dict(r) if r else None

    def evaluations(self, limit=50):
        rows = self.conn.execute("SELECT id,created,symbol,interval,strategy,passed,label FROM evaluations "
                                 "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    # ---------- órdenes ----------
    def _expire(self):
        ttl = dt.timedelta(minutes=self.cfg["proposal_ttl_minutes"])
        now = dt.datetime.now(UTC)
        for r in self.conn.execute("SELECT id, created FROM orders WHERE status='proposed'").fetchall():
            if now - dt.datetime.fromisoformat(r["created"]) > ttl:
                self.conn.execute("UPDATE orders SET status='expired' WHERE id=?", (r["id"],))
                self._audit("techmac", "order_expired", {"id": r["id"]})

    def order(self, oid):
        r = self.conn.execute("SELECT * FROM orders WHERE id=?", (int(oid),)).fetchone()
        return dict(r) if r else None

    def risk_checks(self, symbol, qty, entry, stop, target, evaluation_id, exclude_id=None):
        cfg, reasons = self.cfg, []
        if C.kill_switch_on(self.home):
            reasons.append("Interruptor de emergencia (KILL) activado.")
        if cfg["allowed_symbols"] and symbol not in cfg["allowed_symbols"]:
            reasons.append("%s no está en allowed_symbols." % symbol)
        if not stop < entry:
            reasons.append("El stop debe estar por debajo de la entrada (solo compras).")
        risk = qty * (entry - stop)
        if risk > cfg["max_loss_per_trade_usd"]:
            reasons.append("Pérdida al stop $%.2f > máximo por operación $%.2f." % (risk, cfg["max_loss_per_trade_usd"]))
        if cfg["min_reward_risk"] > 0:
            if target is None:
                reasons.append("Falta el objetivo (min_reward_risk > 0).")
            elif entry > stop and (target - entry) / (entry - stop) < cfg["min_reward_risk"] - 1e-9:
                reasons.append("Beneficio/riesgo %.2f < %.2f." % ((target - entry) / (entry - stop), cfg["min_reward_risk"]))
        value = qty * entry
        cap = cfg["account_equity"] * cfg["max_position_pct"] / 100.0
        if value > cap:
            reasons.append("Posición $%.2f > %.0f %% de la cuenta ($%.2f)." % (value, cfg["max_position_pct"], cap))
        today = str(ny_now().date())
        ex = exclude_id or -1
        n_today = self.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE ny_date=? AND status IN ('approved','open','closed') AND id<>?",
            (today, ex)).fetchone()[0]
        if n_today >= cfg["max_trades_per_day"]:
            reasons.append("Ya hay %d operaciones hoy (máx. %d)." % (n_today, cfg["max_trades_per_day"]))
        n_open = self.conn.execute("SELECT COUNT(*) FROM orders WHERE status IN ('approved','open') AND id<>?",
                                   (ex,)).fetchone()[0]
        if n_open >= cfg["max_open_positions"]:
            reasons.append("Ya hay %d posiciones abiertas o aprobadas (máx. %d)." % (n_open, cfg["max_open_positions"]))
        realized = self.conn.execute("SELECT COALESCE(SUM(pnl),0) FROM orders WHERE status='closed' AND ny_date=?",
                                     (today,)).fetchone()[0]
        open_risk = self.conn.execute("SELECT COALESCE(SUM(risk_usd),0) FROM orders WHERE status IN ('approved','open') "
                                      "AND id<>?", (ex,)).fetchone()[0]
        worst = max(0.0, -realized) + open_risk + risk
        if worst > cfg["max_daily_loss_usd"]:
            reasons.append("Peor caso del día $%.2f (pérdida realizada + riesgo abierto + esta) > límite diario $%.2f."
                           % (worst, cfg["max_daily_loss_usd"]))
        if cfg["require_validated_strategy"]:
            ev = self.evaluation(evaluation_id) if evaluation_id is not None else None
            if ev is None:
                reasons.append("Falta una evaluación walk-forward (evaluation_id) que respalde la orden.")
            else:
                age = dt.datetime.now(UTC) - dt.datetime.fromisoformat(ev["created"])
                if not ev["passed"]:
                    reasons.append("La evaluación #%d fue RECHAZADA." % ev["id"])
                port = ev["symbol"].startswith("PORT:") and symbol in ev["symbol"][5:].split(",")
                if ev["symbol"] != symbol and not port:
                    reasons.append("La evaluación #%d es de %s, no de %s." % (ev["id"], ev["symbol"], symbol))
                if age.days > cfg["max_evaluation_age_days"]:
                    reasons.append("La evaluación #%d tiene %d días (máx. %d)." % (ev["id"], age.days,
                                                                                    cfg["max_evaluation_age_days"]))
        return risk, reasons

    def propose(self, symbol, qty, entry, stop, target=None, evaluation_id=None, note="", actor="claude"):
        symbol = V.symbol(symbol)
        qty = int(V.number(qty, "qty", 1, 1_000_000, True))
        entry = V.number(entry, "entry", 0.0001, 1e7)
        stop = V.number(stop, "stop", 0.0001, 1e7)
        target = None if target is None else V.number(target, "target", 0.0001, 1e7)
        evaluation_id = None if evaluation_id is None else int(V.number(evaluation_id, "evaluation_id", 1, 1e12, True))
        note = V.text(note, "note")
        actor = V.text(actor, "actor", 40) or "desconocido"
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._expire()
            risk, reasons = self.risk_checks(symbol, qty, entry, stop, target, evaluation_id)
            payload = {"symbol": symbol, "qty": qty, "entry": entry, "stop": stop, "target": target,
                       "evaluation_id": evaluation_id, "risk_usd": round(risk, 2)}
            if reasons:
                self._audit(actor, "order_blocked", dict(payload, reasons=reasons))
                self.conn.execute("COMMIT")
                raise RiskBlocked(reasons)
            cur = self.conn.execute(
                "INSERT INTO orders(created,ny_date,symbol,side,qty,entry,stop,target,risk_usd,evaluation_id,note,status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?, 'proposed')",
                (_now(), str(ny_now().date()), symbol, "buy", qty, entry, stop, target, round(risk, 2),
                 evaluation_id, note))
            oid = cur.lastrowid
            self._audit(actor, "order_proposed", dict(payload, id=oid))
            self.conn.execute("COMMIT")
        except RiskBlocked:
            raise
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return self.order(oid)

    def approve(self, oid, typed, actor="humano-terminal"):
        """Solo la CLI interactiva llama a esto. typed debe ser exactamente la frase de confirmación."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._expire()
            o = self.order(oid)
            if o is None or o["status"] != "proposed":
                raise RiskBlocked(["La orden #%s no está pendiente (estado: %s)." % (oid, o and o["status"])])
            if typed.strip() != confirmation_phrase(o):
                self._audit(actor, "approve_wrong_phrase", {"id": o["id"]})
                self.conn.execute("COMMIT")
                raise RiskBlocked(["La frase no coincide. No se aprobó nada."])
            _risk, reasons = self.risk_checks(o["symbol"], o["qty"], o["entry"], o["stop"], o["target"],
                                              o["evaluation_id"], exclude_id=o["id"])
            if reasons:
                self._audit(actor, "approve_blocked", {"id": o["id"], "reasons": reasons})
                self.conn.execute("COMMIT")
                raise RiskBlocked(reasons)
            self.conn.execute("UPDATE orders SET status='approved', approved_at=? WHERE id=?", (_now(), o["id"]))
            self._audit(actor, "order_approved", {"id": o["id"], "phrase": confirmation_phrase(o)})
            self.conn.execute("COMMIT")
        except RiskBlocked:
            raise
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return self.order(oid)

    def _transition(self, oid, allowed, new_status, actor, action, **fields):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            o = self.order(oid)
            if o is None or o["status"] not in allowed:
                raise RiskBlocked(["La orden #%s no admite esta acción (estado: %s)." % (oid, o and o["status"])])
            sets = ", ".join(["status=?"] + ["%s=?" % k for k in fields])
            self.conn.execute("UPDATE orders SET %s WHERE id=?" % sets, [new_status, *fields.values(), o["id"]])
            self._audit(actor, action, dict(fields, id=o["id"]))
            self.conn.execute("COMMIT")
        except RiskBlocked:
            raise
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return self.order(oid)

    def reject(self, oid, actor="humano-terminal"):
        return self._transition(oid, ("proposed", "approved"), "rejected", actor, "order_rejected")

    def record_fill(self, oid, price, qty=None, actor="humano-terminal"):
        o = self.order(oid)
        if o is None:
            raise RiskBlocked(["No existe la orden #%s." % oid])
        price = V.number(price, "precio", 0.0001, 1e7)
        qty = o["qty"] if qty is None else int(V.number(qty, "qty", 1, o["qty"], True))
        return self._transition(oid, ("approved",), "open", actor, "order_filled", fill_price=price, fill_qty=qty)

    def record_exit(self, oid, price, actor="humano-terminal"):
        o = self.order(oid)
        if o is None or o["status"] != "open":
            raise RiskBlocked(["La orden #%s no está abierta." % oid])
        price = V.number(price, "precio", 0.0001, 1e7)
        pnl = round(o["fill_qty"] * (price - o["fill_price"]), 2)
        return self._transition(oid, ("open",), "closed", actor, "order_closed", exit_price=price, pnl=pnl,
                                closed_at=_now())

    def status(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self._expire()
        self.conn.execute("COMMIT")
        rows = [dict(r) for r in self.conn.execute(
            "SELECT id,created,symbol,qty,entry,stop,target,risk_usd,evaluation_id,status,fill_price,exit_price,pnl "
            "FROM orders ORDER BY id DESC LIMIT 50")]
        closed = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(pnl),0), "
                                   "COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0) FROM orders "
                                   "WHERE status='closed'").fetchone()
        r_rows = self.conn.execute("SELECT pnl, fill_qty, fill_price, stop FROM orders WHERE status='closed'").fetchall()
        rs = [r["pnl"] / (r["fill_qty"] * (r["fill_price"] - r["stop"])) for r in r_rows
              if r["fill_price"] > r["stop"]]
        return {"kill_switch": C.kill_switch_on(self.home), "orders": rows,
                "closed_trades": closed[0], "realized_pnl": round(closed[1], 2),
                "win_rate_pct": round(100.0 * closed[2] / closed[0], 1) if closed[0] else None,
                "live_expectancy_r": round(sum(rs) / len(rs), 4) if rs else None,
                "limits": {k: self.cfg[k] for k in ("account_equity", "max_loss_per_trade_usd", "max_daily_loss_usd",
                                                     "max_trades_per_day", "max_open_positions", "min_reward_risk",
                                                     "max_position_pct", "require_validated_strategy")}}
