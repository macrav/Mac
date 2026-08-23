"""
Base de datos de sorteos de KINELO (SQLite).

Un sorteo = 20 números del 1 al 80, sin repetición, cada 5 minutos.
Se guardan de dos formas a la vez:

  - `numbers_csv`: los 20 números ordenados, en texto, para leerlos rápido.
  - `bitmask`:     entero de 80 bits, 1 = el número salió. Permite consultas
                   y conteos muy rápidos sin parsear texto.

Guardar el bitmask hace que contar frecuencias sobre cientos de miles de
sorteos sea cuestión de milisegundos.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from paytable import DRAWN, POOL_SIZE

DEFAULT_DB = Path(__file__).parent / "data" / "kinelo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    draw_id      INTEGER PRIMARY KEY,   -- número de sorteo oficial
    drawn_at     TEXT    NOT NULL,      -- ISO-8601, hora de Lima
    numbers_csv  TEXT    NOT NULL,      -- "3,7,11,..." 20 números ordenados
    bitmask      BLOB    NOT NULL,      -- 10 bytes = 80 bits
    source       TEXT    NOT NULL,      -- de dónde salió el dato
    ingested_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_draws_time ON draws(drawn_at);

-- Frecuencia acumulada por número. Es una vista materializada barata que se
-- recalcula con rebuild_frequencies().
CREATE TABLE IF NOT EXISTS number_stats (
    number       INTEGER PRIMARY KEY CHECK (number BETWEEN 1 AND 80),
    times_drawn  INTEGER NOT NULL DEFAULT 0,
    last_draw_id INTEGER
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at     TEXT NOT NULL,
    source     TEXT NOT NULL,
    inserted   INTEGER NOT NULL,
    skipped    INTEGER NOT NULL,
    note       TEXT
);
"""


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def to_bitmask(numbers: Sequence[int]) -> bytes:
    """Convierte 20 números en 10 bytes (80 bits, bit i = número i+1)."""
    mask = 0
    for n in numbers:
        if not 1 <= n <= POOL_SIZE:
            raise ValueError(f"número fuera de rango 1..80: {n}")
        if mask >> (n - 1) & 1:
            raise ValueError(f"número repetido en el sorteo: {n}")
        mask |= 1 << (n - 1)
    return mask.to_bytes(10, "little")


def from_bitmask(blob: bytes) -> list[int]:
    mask = int.from_bytes(blob, "little")
    return [i + 1 for i in range(POOL_SIZE) if mask >> i & 1]


def validate_draw(numbers: Sequence[int]) -> list[int]:
    """Un sorteo válido es exactamente 20 números distintos del 1 al 80."""
    nums = sorted(numbers)
    if len(nums) != DRAWN:
        raise ValueError(f"un sorteo tiene {DRAWN} números, llegaron {len(nums)}")
    if len(set(nums)) != DRAWN:
        raise ValueError("hay números repetidos en el sorteo")
    if nums[0] < 1 or nums[-1] > POOL_SIZE:
        raise ValueError("hay números fuera del rango 1..80")
    return nums


def insert_draws(
    conn: sqlite3.Connection,
    draws: Iterable[tuple[int, str, Sequence[int]]],
    source: str,
) -> tuple[int, int]:
    """
    Inserta sorteos. Cada uno es (draw_id, drawn_at_iso, numeros).
    Los draw_id que ya existen se ignoran, así que se puede re-correr sin miedo.
    Devuelve (insertados, omitidos).
    """
    now = datetime.now().isoformat(timespec="seconds")
    inserted = skipped = 0
    for draw_id, drawn_at, numbers in draws:
        nums = validate_draw(numbers)
        cur = conn.execute(
            """INSERT OR IGNORE INTO draws
               (draw_id, drawn_at, numbers_csv, bitmask, source, ingested_at)
               VALUES (?,?,?,?,?,?)""",
            (draw_id, drawn_at, ",".join(map(str, nums)),
             to_bitmask(nums), source, now),
        )
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.execute(
        "INSERT INTO ingest_log (ran_at, source, inserted, skipped) VALUES (?,?,?,?)",
        (now, source, inserted, skipped),
    )
    conn.commit()
    return inserted, skipped


def rebuild_frequencies(conn: sqlite3.Connection) -> None:
    """Recalcula number_stats desde cero a partir de la tabla draws."""
    counts = [0] * (POOL_SIZE + 1)
    last = [None] * (POOL_SIZE + 1)
    for row in conn.execute("SELECT draw_id, bitmask FROM draws ORDER BY draw_id"):
        for n in from_bitmask(row["bitmask"]):
            counts[n] += 1
            last[n] = row["draw_id"]
    conn.execute("DELETE FROM number_stats")
    conn.executemany(
        "INSERT INTO number_stats (number, times_drawn, last_draw_id) VALUES (?,?,?)",
        [(n, counts[n], last[n]) for n in range(1, POOL_SIZE + 1)],
    )
    conn.commit()


def load_matrix(conn: sqlite3.Connection, limit: int | None = None) -> list[list[int]]:
    """Todos los sorteos como lista de listas de números, en orden cronológico."""
    sql = "SELECT bitmask FROM draws ORDER BY draw_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [from_bitmask(r["bitmask"]) for r in conn.execute(sql)]


def count_draws(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM draws").fetchone()["n"]
