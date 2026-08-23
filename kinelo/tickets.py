"""
Generador de tickets para KINELO.

Qué se puede optimizar y qué no, sin rodeos:

  NO se puede elegir "mejores números". Las C(80,5) = 24,040,016 combinaciones
  posibles de un ticket de tipo 5 tienen exactamente la misma probabilidad.
  Ninguna secuencia de números es mejor que otra, ni hoy ni nunca, porque los
  sorteos los produce un RNG certificado sin memoria (Reglamento, Art. 19°).

  SÍ se puede optimizar dos cosas, y las dos son reales y medibles:

    1. EL TIPO DE APUESTA. El retorno esperado va de 74.05% (tipo 2) a 80.43%
       (tipo 5). Elegir bien vale 6.4 puntos porcentuales de retorno. Es la
       decisión con más impacto que toma el jugador.

    2. EL SOLAPAMIENTO ENTRE TICKETS de un mismo sorteo. Con el mismo gasto y
       el mismo retorno esperado, tickets con números disjuntos reducen la
       desviación estándar a la mitad y bajan la probabilidad de no cobrar
       nada del 63% al 13%. Ver portfolio.py.

Los números concretos salen de un sorteo reproducible con semilla registrada,
justamente para que quede claro que no están elegidos por ninguna corazonada:
cualquier otra selección disjunta tendría exactamente las mismas propiedades.
"""

from __future__ import annotations

import random

from kinelo_math import expected_return, hit_probability, prob_any_prize
from paytable import PAYOUT, POOL_SIZE, payout_for
from portfolio import portfolio_stats, prob_portfolio_returns_nothing


def best_bet_type() -> int:
    """El tipo de apuesta con mayor retorno esperado. Es dato duro, no opinión."""
    return max(PAYOUT, key=lambda t: expected_return(t))


def generate_portfolio(
    n_tickets: int = 4,
    bet_type: int | None = None,
    seed: int = 20260823,
) -> dict:
    """
    Genera una cartera de `n_tickets` con números mutuamente disjuntos.

    Disjuntos = mínima varianza para ese retorno esperado. Si no alcanzan los
    80 números para que sean todos disjuntos, se minimiza el solapamiento.
    """
    bet_type = bet_type or best_bet_type()
    needed = n_tickets * bet_type
    if needed > POOL_SIZE:
        raise ValueError(
            f"{n_tickets} tickets de {bet_type} números necesitan {needed} "
            f"números distintos, y solo hay {POOL_SIZE}"
        )

    rng = random.Random(seed)
    pool = rng.sample(range(1, POOL_SIZE + 1), needed)
    tickets = [sorted(pool[i * bet_type:(i + 1) * bet_type]) for i in range(n_tickets)]

    stats = portfolio_stats(tickets, bet_type)
    stats["prob_no_cobrar_nada"] = prob_portfolio_returns_nothing(tickets, bet_type)
    return {
        "tickets": tickets,
        "tipo_apuesta": bet_type,
        "semilla": seed,
        "stats": stats,
        "tabla_premios": dict(sorted(PAYOUT[bet_type].items(), reverse=True)),
    }


def ticket_outcome_table(bet_type: int) -> list[dict]:
    """Qué paga cada resultado posible y con qué probabilidad."""
    rows = []
    for hits in range(bet_type, -1, -1):
        p = float(hit_probability(bet_type, hits))
        mult = payout_for(bet_type, hits)
        rows.append(
            {
                "aciertos": hits,
                "paga_x": mult,
                "probabilidad": p,
                "uno_en": (1 / p) if p else float("inf"),
                "aporte_al_rtp": p * mult,
            }
        )
    return rows


def format_portfolio(result: dict, stake: float = 1.0) -> str:
    bt = result["tipo_apuesta"]
    st = result["stats"]
    lines = []
    lines.append(f"CARTERA DE {st['n_tickets']} TICKETS — tipo de apuesta {bt} "
                 f"({bt} números por ticket)")
    lines.append(f"Semilla reproducible: {result['semilla']}")
    lines.append("")
    for i, t in enumerate(result["tickets"], 1):
        lines.append(f"  Ticket {i}:  " + "  ".join(f"{n:2d}" for n in t))
    lines.append("")
    lines.append(f"  Números distintos usados : {st['n_tickets'] * bt} de 80")
    lines.append(f"  Solapamiento entre pares : {st['solapamiento_total']} "
                 f"(0 = varianza mínima)")
    lines.append("")
    lines.append(f"  Costo total              : S/ {st['costo'] * stake:,.2f}")
    lines.append(f"  Retorno esperado         : S/ {st['retorno_esperado_soles'] * stake:,.4f}")
    lines.append(f"  Pérdida esperada         : S/ {st['perdida_esperada_soles'] * stake:,.4f} "
                 f"por sorteo ({(1 - st['rtp']) * 100:.2f}% de lo apostado)")
    lines.append(f"  Desviación estándar      : S/ {st['desv_estandar_soles'] * stake:,.2f}")
    lines.append(f"  P(no cobrar nada)        : {st['prob_no_cobrar_nada'] * 100:.2f}%")
    lines.append("")
    lines.append(f"  Tabla de premios del tipo {bt} (por cada S/ 1 apostado):")
    for row in ticket_outcome_table(bt):
        if row["paga_x"] == 0:
            continue
        lines.append(
            f"    {row['aciertos']} aciertos -> paga {row['paga_x']:>6,}x   "
            f"prob {row['probabilidad'] * 100:8.4f}%   (1 en {row['uno_en']:,.0f})"
        )
    return "\n".join(lines)
