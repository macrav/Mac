"""
Matemática de una cartera de varios tickets jugados en el MISMO sorteo.

Esta es la única parte del juego donde una decisión del jugador cambia algo
medible, así que vale la pena hacerla bien.

El retorno esperado de una cartera es la suma de los retornos esperados de
cada ticket, y eso no depende de qué números se elijan: todas las
combinaciones son equiprobables. Lo que SÍ depende de la elección es la
VARIANZA de la cartera.

Dos tickets que comparten números aciertan y fallan juntos: sus resultados
están correlacionados positivamente, y la cartera se vuelve más volátil. Dos
tickets con números disjuntos están correlacionados NEGATIVAMENTE (los 20
números del sorteo son un recurso limitado: los que se lleva uno no se los
lleva el otro), y la cartera se vuelve más estable.

Mismo retorno esperado, menos varianza. Para "lo más seguro posible" con un
presupuesto dado, esto es literalmente lo único que se puede optimizar.

Todo se calcula exacto con la hipergeométrica multivariante, sin simular.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import combinations
from math import comb

from kinelo_math import expected_return, hit_probability, variance_of_return
from paytable import DRAWN, POOL_SIZE, payout_for


def joint_hit_distribution(
    n_a: int, n_b: int, overlap: int
) -> dict[tuple[int, int], Fraction]:
    """
    Distribución conjunta exacta de (aciertos_A, aciertos_B) para dos tickets
    de tamaños n_a y n_b que comparten `overlap` números.

    Se parte el universo de 80 números en cuatro bloques disjuntos:
        S      = compartidos por A y B        (overlap)
        Aonly  = solo de A                    (n_a - overlap)
        Bonly  = solo de B                    (n_b - overlap)
        resto  = ninguno de los dos
    y se aplica la hipergeométrica multivariante sobre los 20 extraídos.
    """
    if overlap > min(n_a, n_b):
        raise ValueError("el solapamiento no puede exceder el tamaño de los tickets")
    s_sz = overlap
    a_sz = n_a - overlap
    b_sz = n_b - overlap
    rest = POOL_SIZE - s_sz - a_sz - b_sz
    total = comb(POOL_SIZE, DRAWN)

    dist: dict[tuple[int, int], Fraction] = {}
    for s in range(min(s_sz, DRAWN) + 1):
        for a in range(min(a_sz, DRAWN - s) + 1):
            for b in range(min(b_sz, DRAWN - s - a) + 1):
                r = DRAWN - s - a - b
                if r < 0 or r > rest:
                    continue
                ways = comb(s_sz, s) * comb(a_sz, a) * comb(b_sz, b) * comb(rest, r)
                if not ways:
                    continue
                key = (s + a, s + b)
                dist[key] = dist.get(key, Fraction(0)) + Fraction(ways, total)
    return dist


def covariance(bet_type: int, overlap: int) -> Fraction:
    """Covarianza exacta entre los pagos de dos tickets del mismo tipo."""
    dist = joint_hit_distribution(bet_type, bet_type, overlap)
    exy = sum(
        p * payout_for(bet_type, ha) * payout_for(bet_type, hb)
        for (ha, hb), p in dist.items()
    )
    mean = expected_return(bet_type)
    return exy - mean * mean


def portfolio_stats(tickets: list[list[int]], bet_type: int, stake: float = 1.0) -> dict:
    """
    Retorno esperado, varianza y desviación estándar exactos de una cartera.

    Var(sum) = sum Var(i) + 2 * sum_{i<j} Cov(i,j)
    """
    m = len(tickets)
    for t in tickets:
        if len(set(t)) != bet_type:
            raise ValueError(f"cada ticket debe tener {bet_type} números distintos")

    mean_one = expected_return(bet_type)
    var_one = variance_of_return(bet_type)

    total_mean = mean_one * m
    total_var = var_one * m
    overlaps = []
    for i, j in combinations(range(m), 2):
        ov = len(set(tickets[i]) & set(tickets[j]))
        overlaps.append(ov)
        total_var += 2 * covariance(bet_type, ov)

    sd = float(total_var) ** 0.5
    cost = m * stake
    return {
        "n_tickets": m,
        "tipo_apuesta": bet_type,
        "costo": cost,
        "retorno_esperado_soles": float(total_mean) * stake,
        "perdida_esperada_soles": cost - float(total_mean) * stake,
        "rtp": float(total_mean) / m,
        "varianza": float(total_var),
        "desv_estandar_soles": sd * stake,
        "solapamientos_por_par": overlaps,
        "solapamiento_total": sum(overlaps),
    }


def prob_portfolio_returns_nothing(tickets: list[list[int]], bet_type: int) -> float:
    """
    Probabilidad exacta de que NINGUNO de los tickets cobre nada.

    Solo se calcula en forma cerrada para carteras disjuntas, que es el caso
    que recomendamos; para carteras solapadas se indica que hace falta simular.
    """
    union = set()
    for t in tickets:
        union |= set(t)
    if len(union) != len(tickets) * bet_type:
        raise ValueError("solo se calcula exacto para tickets disjuntos")

    # Con tickets disjuntos, los aciertos se reparten por hipergeométrica
    # multivariante sobre los bloques; hay que enumerar los repartos en los
    # que todos los tickets caen en una casilla sin premio.
    losing = [h for h in range(bet_type + 1) if payout_for(bet_type, h) == 0]
    m = len(tickets)
    rest = POOL_SIZE - m * bet_type
    total = comb(POOL_SIZE, DRAWN)

    def rec(idx: int, remaining: int) -> int:
        if idx == m:
            return comb(rest, remaining) if 0 <= remaining <= rest else 0
        acc = 0
        for h in losing:
            if h <= remaining:
                acc += comb(bet_type, h) * rec(idx + 1, remaining - h)
        return acc

    return rec(0, DRAWN) / total


def compare_overlap_designs(bet_type: int, m: int = 4) -> list[dict]:
    """
    Compara carteras de `m` tickets con distintos grados de solapamiento.

    Demuestra numéricamente que el retorno esperado es idéntico en todos los
    diseños y que solo cambia la varianza.
    """
    out = []
    max_ov = bet_type
    for ov in range(max_ov + 1):
        # Construimos m tickets donde cada par comparte exactamente `ov`
        # números: un núcleo común de tamaño `ov` y colas disjuntas.
        core = list(range(1, ov + 1))
        tickets, nxt = [], ov + 1
        for _ in range(m):
            tail = list(range(nxt, nxt + bet_type - ov))
            nxt += bet_type - ov
            tickets.append(core + tail)
        if nxt - 1 > POOL_SIZE:
            continue
        st = portfolio_stats(tickets, bet_type)
        out.append(
            {
                "solapamiento_por_par": ov,
                "retorno_esperado_soles": st["retorno_esperado_soles"],
                "desv_estandar_soles": st["desv_estandar_soles"],
                "varianza": st["varianza"],
            }
        )
    return out
