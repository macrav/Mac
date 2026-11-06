"""Almacén local de velas (SQLite) con controles de integridad."""

import csv
import datetime as dt
import hashlib
import io
import math
import sqlite3
from pathlib import Path
from typing import NamedTuple

from . import config as C
from . import validate as V
from .timeutil import UTC, ny_to_epoch, to_ny

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars(
  symbol TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  volume REAL NOT NULL DEFAULT 0, source TEXT NOT NULL,
  PRIMARY KEY(symbol, interval, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS imports(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
  source TEXT NOT NULL, rows INTEGER NOT NULL, rejected INTEGER NOT NULL, sha256 TEXT NOT NULL);
"""


class Bar(NamedTuple):
    ts: int
    o: float
    h: float
    l: float
    c: float
    v: float


def bar_ok(b):
    vals = (b.o, b.h, b.l, b.c)
    if not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in vals):
        return False
    if not (math.isfinite(b.v) and b.v >= 0):
        return False
    return b.l <= min(b.o, b.c) and b.h >= max(b.o, b.c) and b.l <= b.h


class Series:
    """Serie de velas ordenada, con fecha y minuto de Nueva York precalculados."""

    def __init__(self, symbol, interval, bars):
        self.symbol = symbol
        self.interval = interval
        self.step = V.INTERVALS[interval]
        self.intraday = interval != "1d"
        self.bars = list(bars)
        if self.intraday:
            ny = [to_ny(b.ts) for b in self.bars]
            self.dates = [d.date() for d in ny]
            self.minutes = [d.hour * 60 + d.minute for d in ny]
        else:
            self.dates = [dt.datetime.fromtimestamp(b.ts, UTC).date() for b in self.bars]
            self.minutes = [None] * len(self.bars)

    def __len__(self):
        return len(self.bars)

    def regular_session(self):
        """Solo velas de 9:30 a 16:00 (intradía)."""
        if not self.intraday:
            return self
        keep = [b for b, m in zip(self.bars, self.minutes) if 570 <= m < 960]
        return Series(self.symbol, self.interval, keep)

    def between(self, start=None, end=None):
        keep = [b for b, d in zip(self.bars, self.dates)
                if (start is None or d >= start) and (end is None or d <= end)]
        return Series(self.symbol, self.interval, keep)

    def fingerprint(self):
        h = hashlib.sha256()
        for b in self.bars:
            h.update(("%d,%.6f,%.6f,%.6f,%.6f,%.0f;" % b).encode())
        return h.hexdigest()

    def unique_dates(self):
        out = []
        for d in self.dates:
            if not out or out[-1] != d:
                out.append(d)
        return out


class Store:
    def __init__(self, h=None):
        self.home = C.secure_dir(h or C.home())
        self.path = Path(self.home) / "bars.db"
        new = not self.path.exists()
        self.conn = sqlite3.connect(str(self.path))
        if new:
            C.secure_file(self.path)
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def upsert(self, symbol, interval, bars, source, raw_bytes=b""):
        symbol, interval = V.symbol(symbol), V.interval(interval)
        good, rejected = [], 0
        for b in bars:
            if bar_ok(b):
                good.append(b)
            else:
                rejected += 1
        with self.conn:
            self.conn.executemany(
                "INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,interval,ts) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                "volume=excluded.volume, source=excluded.source",
                [(symbol, interval, int(b.ts), b.o, b.h, b.l, b.c, b.v, source) for b in good])
            self.conn.execute(
                "INSERT INTO imports(at,symbol,interval,source,rows,rejected,sha256) VALUES(?,?,?,?,?,?,?)",
                (dt.datetime.now(UTC).isoformat(timespec="seconds"), symbol, interval, source,
                 len(good), rejected, hashlib.sha256(raw_bytes).hexdigest()))
        return len(good), rejected

    def load(self, symbol, interval, start=None, end=None, regular_only=True):
        symbol, interval = V.symbol(symbol), V.interval(interval)
        rows = self.conn.execute(
            "SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND interval=? ORDER BY ts",
            (symbol, interval)).fetchall()
        s = Series(symbol, interval, [Bar(*r) for r in rows])
        if regular_only:
            s = s.regular_session()
        if start or end:
            s = s.between(start, end)
        return s

    def inventory(self, symbol=None):
        q = ("SELECT symbol, interval, COUNT(*), MIN(ts), MAX(ts), GROUP_CONCAT(DISTINCT source) "
             "FROM bars %s GROUP BY symbol, interval ORDER BY symbol, interval")
        if symbol:
            rows = self.conn.execute(q % "WHERE symbol=?", (V.symbol(symbol),)).fetchall()
        else:
            rows = self.conn.execute(q % "").fetchall()
        out = []
        for sym, iv, n, t0, t1, src in rows:
            s = self.load(sym, iv, regular_only=True)
            out.append({"symbol": sym, "interval": iv, "bars": n, "regular_bars": len(s),
                        "sessions": len(s.unique_dates()),
                        "first": str(s.dates[0]) if len(s) else None,
                        "last": str(s.dates[-1]) if len(s) else None,
                        "sources": src, "gaps": gap_report(s) if len(s) else {}})
        return out


def gap_report(series):
    """Sesiones intradía incompletas (menos velas que lo normal)."""
    if not series.intraday:
        return {}
    per_day = {}
    for d in series.dates:
        per_day[d] = per_day.get(d, 0) + 1
    if not per_day:
        return {}
    full = max(per_day.values())
    short = [str(d) for d, n in per_day.items() if n < full * 0.9]
    return {"bars_per_full_session": full, "short_sessions": len(short), "examples": short[:5]}


MAX_CSV_BYTES = 200 * 1024 * 1024


def parse_csv(raw, interval, tz="NY"):
    """CSV con columnas date/datetime/timestamp, open, high, low, close[, volume]."""
    if len(raw) > MAX_CSV_BYTES:
        raise V.ValidationError("CSV demasiado grande.")
    text = raw.decode("utf-8-sig", errors="strict")
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().lower() for h in next(reader)]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    it = col("timestamp", "datetime", "date", "time", "fecha")
    io_, ih, il, ic = col("open"), col("high"), col("low"), col("close")
    iv = col("volume", "vol")
    if None in (it, io_, ih, il, ic):
        raise V.ValidationError("El CSV necesita columnas date|datetime|timestamp, open, high, low, close.")
    bars, bad = [], 0
    for row in reader:
        if not row or all(not x.strip() for x in row):
            continue
        try:
            ts = _parse_ts(row[it].strip(), interval, tz)
            vol = float(row[iv]) if iv is not None and row[iv].strip() else 0.0
            bars.append(Bar(ts, float(row[io_]), float(row[ih]), float(row[il]), float(row[ic]), vol))
        except (ValueError, IndexError):
            bad += 1
    return bars, bad


def _parse_ts(s, interval, tz):
    if s.isdigit():
        n = int(s)
        return n // 1000 if n > 10 ** 11 else n
    if interval == "1d":
        d = dt.date.fromisoformat(s[:10])
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
    s = s.replace("T", " ").replace("Z", "+00:00")
    full = dt.datetime.fromisoformat(s)
    if full.tzinfo is not None:            # la fecha trae su propia zona horaria
        return int(full.timestamp())
    local = full.replace(microsecond=0)
    if tz.upper() == "UTC":
        return int(local.replace(tzinfo=UTC).timestamp())
    return ny_to_epoch(local)
