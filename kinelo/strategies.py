"""
Estrategias de predicción para KINELO, implementadas en serio.

Aquí están las que realmente se usan y se venden por internet. Todas mantienen
su estado de forma incremental: `observe` recibe cada sorteo en orden y `pick`
se llama ANTES de observar el sorteo que se está prediciendo, así que ninguna
puede mirar el futuro. Eso es lo que hace que el backtest signifique algo.

El objetivo del módulo no es que alguna gane. Es medir, con el mismo criterio
para todas, cuánto se separan del azar. La comparación contra `RandomPick` es
la que manda.
"""

from __future__ import annotations

import random
from collections import Counter, deque

from paytable import POOL_SIZE

ALL_NUMBERS = list(range(1, POOL_SIZE + 1))


class Strategy:
    """
    Interfaz común.

    Ciclo de vida por sorteo:  pick(...)  ->  observe(sorteo_real)
    """

    name = "base"

    def reset(self) -> None:
        pass

    def observe(self, draw: list[int]) -> None:
        pass

    def pick(self, k: int, rng: random.Random) -> list[int]:
        raise NotImplementedError


class RandomPick(Strategy):
    """Números al azar. Es la línea base contra la que se mide todo."""
    name = "azar"

    def pick(self, k, rng):
        return rng.sample(ALL_NUMBERS, k)


class Fixed(Strategy):
    """Siempre los mismos números. Prueba que la elección concreta da igual."""

    def __init__(self, numbers: list[int]):
        self.numbers = list(numbers)
        self.name = f"fijos({','.join(map(str, numbers[:3]))}…)"

    def pick(self, k, rng):
        if k > len(self.numbers):
            raise ValueError("la jugada fija no tiene suficientes números")
        return self.numbers[:k]


class _RollingCounts(Strategy):
    """Base para estrategias que necesitan frecuencias en ventana móvil."""

    def __init__(self, window: int):
        self.window = window
        self.reset()

    def reset(self):
        self.counts = Counter()
        self.buf: deque[list[int]] = deque()

    def observe(self, draw):
        self.buf.append(draw)
        self.counts.update(draw)
        if len(self.buf) > self.window:
            for n in self.buf.popleft():
                self.counts[n] -= 1


class Hot(_RollingCounts):
    """Los k números más frecuentes de la ventana reciente. 'Seguir la racha'."""

    def __init__(self, window: int = 500):
        super().__init__(window)
        self.name = f"calientes(v={window})"

    def pick(self, k, rng):
        if not self.buf:
            return rng.sample(ALL_NUMBERS, k)
        return sorted(ALL_NUMBERS, key=lambda n: (-self.counts[n], rng.random()))[:k]


class Cold(_RollingCounts):
    """Los k menos frecuentes. 'Ya les toca'. La falacia del jugador, formalizada."""

    def __init__(self, window: int = 500):
        super().__init__(window)
        self.name = f"frios(v={window})"

    def pick(self, k, rng):
        if not self.buf:
            return rng.sample(ALL_NUMBERS, k)
        return sorted(ALL_NUMBERS, key=lambda n: (self.counts[n], rng.random()))[:k]


class LongestGap(Strategy):
    """Los k números que llevan más sorteos sin salir."""
    name = "mas_atrasados"

    def reset(self):
        self.t = 0
        self.last_seen = {n: -1 for n in ALL_NUMBERS}

    def __init__(self):
        self.reset()

    def observe(self, draw):
        for n in draw:
            self.last_seen[n] = self.t
        self.t += 1

    def pick(self, k, rng):
        if self.t == 0:
            return rng.sample(ALL_NUMBERS, k)
        return sorted(ALL_NUMBERS, key=lambda n: (self.last_seen[n], rng.random()))[:k]


class MarkovPair(Strategy):
    """
    Modelo de Markov de primer orden sobre co-ocurrencias.

    Aprende con qué frecuencia el número j aparece en el sorteo siguiente a uno
    donde apareció i, y puntúa los candidatos según el último sorteo observado.
    Es el más sofisticado del conjunto y el que mejor suena sobre el papel.

    La matriz 80x80 se mantiene incrementalmente: al entrar un sorteo se suman
    400 celdas, y al salir de la ventana se restan las mismas 400.
    """

    def __init__(self, window: int = 5000):
        self.window = window
        self.name = f"markov(v={window})"
        self.reset()

    def reset(self):
        self.trans = [[0] * (POOL_SIZE + 1) for _ in range(POOL_SIZE + 1)]
        self.buf: deque[list[int]] = deque()
        self.prev: list[int] | None = None
        self.pairs: deque[tuple[list[int], list[int]]] = deque()

    def observe(self, draw):
        if self.prev is not None:
            for i in self.prev:
                row = self.trans[i]
                for j in draw:
                    row[j] += 1
            self.pairs.append((self.prev, draw))
            if len(self.pairs) > self.window:
                old_a, old_b = self.pairs.popleft()
                for i in old_a:
                    row = self.trans[i]
                    for j in old_b:
                        row[j] -= 1
        self.prev = draw

    def pick(self, k, rng):
        if self.prev is None or len(self.pairs) < 50:
            return rng.sample(ALL_NUMBERS, k)
        score = [0] * (POOL_SIZE + 1)
        for i in self.prev:
            row = self.trans[i]
            for j in ALL_NUMBERS:
                score[j] += row[j]
        return sorted(ALL_NUMBERS, key=lambda n: (-score[n], rng.random()))[:k]


class SumTarget(Strategy):
    """
    Elige un conjunto cuya suma quede cerca de la suma media teórica.

    Estrategia popular en foros de keno. Se implementa para poder medirla, no
    porque tenga fundamento.
    """
    name = "suma_objetivo"

    def pick(self, k, rng):
        target = k * (POOL_SIZE + 1) / 2
        best, best_err = None, float("inf")
        for _ in range(60):
            cand = rng.sample(ALL_NUMBERS, k)
            err = abs(sum(cand) - target)
            if err < best_err:
                best, best_err = cand, err
                if err <= 1:
                    break
        return best


class AntiPopular(Strategy):
    """
    Evita 1-31, que la gente sobre-juega por fechas de cumpleaños.

    En loterías de pozo compartido esto SÍ sirve: no cambia la probabilidad de
    ganar, pero reduce la chance de repartir el premio con otros. En KINELO los
    premios son de cuota fija (un múltiplo de la apuesta), así que no cambia
    absolutamente nada. Se incluye para dejarlo demostrado con números.
    """
    name = "anti_populares"

    def pick(self, k, rng):
        return rng.sample([n for n in ALL_NUMBERS if n > 31], k)


def default_suite(seed_numbers: list[int] | None = None) -> list[Strategy]:
    fixed = seed_numbers or [7, 13, 22, 31, 44, 55, 66, 71, 77, 80]
    return [
        RandomPick(),
        Fixed(fixed),
        Hot(window=200), Hot(window=2000),
        Cold(window=200), Cold(window=2000),
        LongestGap(),
        MarkovPair(window=5000),
        SumTarget(),
        AntiPopular(),
    ]
