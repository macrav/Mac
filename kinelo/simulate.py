"""
Generador de sorteos sintéticos de KINELO.

Sirve para dos cosas concretas:

  1. Validar que la batería de tests y el backtest funcionan: sobre un RNG
     conocido y limpio deben dar exactamente "no hay señal".
  2. Calibrar cuánta desviación es normal por puro azar. Sin esta referencia
     es imposible saber si un patrón del histórico real significa algo.

`biased_draws` permite inyectar un sesgo controlado para comprobar que los
tests SÍ lo detectan cuando existe. Un test que nunca detecta nada no sirve.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from paytable import DRAWN, POOL_SIZE


def fair_draws(n: int, seed: int | None = None) -> list[list[int]]:
    """`n` sorteos de un RNG uniforme e independiente."""
    rng = random.Random(seed)
    pool = list(range(1, POOL_SIZE + 1))
    return [sorted(rng.sample(pool, DRAWN)) for _ in range(n)]


def biased_draws(n: int, hot: dict[int, float], seed: int | None = None) -> list[list[int]]:
    """
    Sorteos con sesgo deliberado.

    `hot` mapea número -> peso relativo (1.0 = normal, 2.0 = doble de probable).
    Solo existe para verificar la sensibilidad de los tests.
    """
    rng = random.Random(seed)
    weights = [hot.get(i, 1.0) for i in range(1, POOL_SIZE + 1)]
    out = []
    for _ in range(n):
        pool = list(range(1, POOL_SIZE + 1))
        w = list(weights)
        picked = []
        for _ in range(DRAWN):
            idx = rng.choices(range(len(pool)), weights=w, k=1)[0]
            picked.append(pool.pop(idx))
            w.pop(idx)
        out.append(sorted(picked))
    return out


def with_timestamps(draws: list[list[int]], start_id: int = 1,
                    start: datetime | None = None) -> list[tuple[int, str, list[int]]]:
    """Añade draw_id y hora cada 5 minutos, como el juego real."""
    start = start or datetime(2026, 1, 1, 6, 0, 0)
    return [
        (start_id + i, (start + timedelta(minutes=5 * i)).isoformat(timespec="seconds"), d)
        for i, d in enumerate(draws)
    ]
