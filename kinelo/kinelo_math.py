"""
Motor matemático exacto de KINELO.

Todo aquí es aritmética exacta con enteros y Fraction: no hay simulación ni
aproximación. La distribución de aciertos es hipergeométrica y se puede
calcular en forma cerrada, así que el retorno esperado de cada tipo de
apuesta es un número exacto, no una estimación.

P(k aciertos | elijo n números) = C(20,k) * C(60,n-k) / C(80,n)

    20 = números que saca el RNG
    60 = números que NO salen
    n  = cuántos números marca el jugador (1..10)
"""

from fractions import Fraction
from math import comb

from paytable import DRAWN, POOL_SIZE, PAYOUT, payout_for


def hit_probability(bet_type: int, hits: int) -> Fraction:
    """Probabilidad exacta de acertar `hits` de `bet_type` números marcados."""
    if not 0 <= hits <= bet_type:
        return Fraction(0)
    misses = POOL_SIZE - DRAWN          # 60
    favorable = comb(DRAWN, hits) * comb(misses, bet_type - hits)
    total = comb(POOL_SIZE, bet_type)
    return Fraction(favorable, total)


def hit_distribution(bet_type: int) -> dict[int, Fraction]:
    """Distribución completa de aciertos para un tipo de apuesta."""
    return {k: hit_probability(bet_type, k) for k in range(bet_type + 1)}


def expected_return(bet_type: int) -> Fraction:
    """
    Retorno esperado por sol apostado (RTP).

    RTP = sum_k  P(k) * payout(k)

    RTP = 1.0 significaría juego justo. Todo lo que esté por debajo es la
    ventaja de la casa.
    """
    return sum(
        hit_probability(bet_type, k) * payout_for(bet_type, k)
        for k in range(bet_type + 1)
    )


def house_edge(bet_type: int) -> Fraction:
    """Ventaja de la casa = 1 - RTP."""
    return Fraction(1) - expected_return(bet_type)


def prob_any_prize(bet_type: int) -> Fraction:
    """Probabilidad de que la jugada cobre algo (payout > 0)."""
    return sum(
        hit_probability(bet_type, k)
        for k in range(bet_type + 1)
        if payout_for(bet_type, k) > 0
    )


def variance_of_return(bet_type: int) -> Fraction:
    """Varianza del retorno por sol apostado. Mide cuán brutal es el swing."""
    mean = expected_return(bet_type)
    second = sum(
        hit_probability(bet_type, k) * payout_for(bet_type, k) ** 2
        for k in range(bet_type + 1)
    )
    return second - mean * mean


def odds_of_jackpot(bet_type: int) -> Fraction:
    """1 en cuántos sorteos se acierta la primera categoría."""
    p = hit_probability(bet_type, bet_type)
    return Fraction(1) / p if p else Fraction(0)


def summary_table() -> list[dict]:
    """Una fila por tipo de apuesta, con todas las métricas que importan."""
    rows = []
    for t in sorted(PAYOUT, reverse=True):
        rtp = expected_return(t)
        var = variance_of_return(t)
        rows.append(
            {
                "tipo": t,
                "rtp": float(rtp),
                "ventaja_casa": float(house_edge(t)),
                "prob_cobrar_algo": float(prob_any_prize(t)),
                "prob_primera_cat": float(hit_probability(t, t)),
                "odds_primera_cat": float(odds_of_jackpot(t)),
                "desv_est": float(var) ** 0.5,
                "rtp_exacto": rtp,
            }
        )
    return rows


def loss_after(bet_type: int, n_plays: int, stake: float = 1.0) -> float:
    """Pérdida esperada tras `n_plays` jugadas. Aritmética simple, sin adornos."""
    return float(house_edge(bet_type)) * n_plays * stake


def prob_ruin_free_streak(bet_type: int, n_plays: int) -> float:
    """Probabilidad de no cobrar absolutamente nada en `n_plays` jugadas."""
    p_nothing = float(Fraction(1) - prob_any_prize(bet_type))
    return p_nothing ** n_plays
