"""
Backtest honesto de estrategias de predicción.

Reglas del backtest, que son las que hacen la diferencia entre medir algo y
engañarse:

  - La estrategia solo ve los sorteos anteriores al que está prediciendo.
  - Todas las estrategias se evalúan sobre exactamente los mismos sorteos.
  - Se reporta el retorno junto con su intervalo de confianza. Un retorno de
    82% sin intervalo no dice nada: la desviación estándar por jugada supera
    el 900% en los tipos altos.

El criterio de éxito es duro y explícito: para afirmar que una estrategia
funciona, su retorno tiene que quedar por encima de 1.0 (no por encima de la
estrategia al azar) con significancia estadística. Superar al azar por poco
no sirve de nada si ambas pierden plata.
"""

from __future__ import annotations

import random
from math import sqrt

from kinelo_math import expected_return
from paytable import payout_for
from strategies import Strategy


def run_backtest(
    draws: list[list[int]],
    strategy: Strategy,
    bet_type: int = 5,
    warmup: int = 500,
    seed: int = 12345,
    stake: float = 1.0,
) -> dict:
    """
    Evalúa una estrategia sorteo a sorteo.

    `warmup` son los sorteos iniciales que la estrategia puede estudiar antes
    de empezar a apostar.
    """
    rng = random.Random(seed)
    if len(draws) <= warmup + 10:
        raise ValueError(
            f"histórico insuficiente: {len(draws)} sorteos, "
            f"se necesitan más de {warmup + 10}"
        )

    strategy.reset()
    hits_hist: dict[int, int] = {}
    staked = won = 0.0
    sum_r = sum_r2 = 0.0
    n = 0

    for t, draw in enumerate(draws):
        if t >= warmup:
            picks = strategy.pick(bet_type, rng)
            if len(set(picks)) != bet_type:
                raise ValueError(
                    f"{strategy.name} devolvió {len(set(picks))} números únicos"
                )
            hits = len(set(picks) & set(draw))
            r = payout_for(bet_type, hits) * stake
            hits_hist[hits] = hits_hist.get(hits, 0) + 1
            staked += stake
            won += r
            sum_r += r / stake
            sum_r2 += (r / stake) ** 2
            n += 1
        strategy.observe(draw)

    mean = sum_r / n
    var = (sum_r2 - n * mean * mean) / (n - 1) if n > 1 else 0.0
    se = sqrt(var / n) if n else 0.0
    theoretical = float(expected_return(bet_type))

    return {
        "estrategia": strategy.name,
        "tipo_apuesta": bet_type,
        "jugadas": n,
        "apostado": staked,
        "ganado": won,
        "resultado_neto": won - staked,
        "retorno": mean,
        "error_estandar": se,
        "ic95_bajo": mean - 1.96 * se,
        "ic95_alto": mean + 1.96 * se,
        "retorno_teorico": theoretical,
        # ¿El retorno observado supera 1.0 con significancia? Esta es LA pregunta.
        "supera_el_punto_de_equilibrio": (mean - 1.96 * se) > 1.0,
        # ¿Se distingue del retorno teórico del azar?
        "z_vs_teorico": (mean - theoretical) / se if se else 0.0,
        "distribucion_aciertos": dict(sorted(hits_hist.items())),
    }


def compare(
    draws: list[list[int]],
    strategies: list[Strategy],
    bet_type: int = 5,
    warmup: int = 500,
    seed: int = 12345,
) -> list[dict]:
    return [run_backtest(draws, s, bet_type, warmup, seed) for s in strategies]


def format_comparison(results: list[dict]) -> str:
    lines = []
    bt = results[0]["tipo_apuesta"]
    n = results[0]["jugadas"]
    teo = results[0]["retorno_teorico"]
    lines.append(f"Backtest — tipo de apuesta {bt}, {n:,} jugadas de S/ 1 por estrategia")
    lines.append(f"Retorno teórico del azar puro: {teo*100:.3f}%")
    lines.append("")
    lines.append(f"{'Estrategia':<26} {'Retorno':>9} {'IC 95%':>19} {'Neto S/':>11} {'¿Gana?':>8}")
    lines.append("-" * 78)
    for r in sorted(results, key=lambda x: -x["retorno"]):
        ic = f"[{r['ic95_bajo']*100:.1f}, {r['ic95_alto']*100:.1f}]"
        gana = "SÍ" if r["supera_el_punto_de_equilibrio"] else "no"
        lines.append(
            f"{r['estrategia']:<26} {r['retorno']*100:>8.2f}% {ic:>19} "
            f"{r['resultado_neto']:>11,.0f} {gana:>8}"
        )
    lines.append("-" * 78)
    winners = [r for r in results if r["supera_el_punto_de_equilibrio"]]
    lines.append(
        f"Estrategias con retorno > 100% estadísticamente significativo: {len(winners)}"
    )
    return "\n".join(lines)
