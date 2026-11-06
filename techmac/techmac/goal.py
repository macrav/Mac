"""Simulador de meta: ¿cuánto tardo en llegar a X y qué probabilidad tengo de quebrar en el camino?

Remuestrea por bloques de 12 meses los retornos mensuales REALES (de una evaluación fuera de muestra
o de comprar y mantener un activo) y los proyecta con tu capital, tus aportes y varios niveles de
apalancamiento. Con apalancamiento se cobra financiación y, si un mes pierde todo, es quiebra.
"""

import random

from . import validate as V


def simulate(monthly, capital, monthly_contribution, target, max_years, leverages, borrow_rate=0.06,
             sims=4000, seed=19, block=12):
    if len(monthly) < 36:
        raise V.ValidationError("Hacen falta al menos 36 meses de retornos (hay %d)." % len(monthly))
    capital = V.number(capital, "capital", 0, 1e10)
    contrib = V.number(monthly_contribution, "aporte mensual", 0, 1e8)
    target = V.number(target, "meta", 1, 1e12)
    max_years = int(V.number(max_years, "años máximos", 1, 60, True))
    if capital <= 0 and contrib <= 0:
        raise V.ValidationError("Necesitas capital inicial o aportes mensuales.")
    levs = [V.number(x, "apalancamiento", 0.25, 5) for x in leverages][:8]
    n, months = len(monthly), max_years * 12
    out = []
    for lev in levs:
        rng = random.Random(seed)
        hit_months, ruined, deep_dd, finals, underwater, end_loss = [], 0, 0, [], 0, 0
        for _ in range(sims):
            eq, peak, invested, reached, dead, dd50, below = capital, capital, capital, None, False, False, False
            m = 0
            while m < months:
                s = rng.randrange(n)
                for j in range(block):
                    if m >= months:
                        break
                    eq += contrib                      # el aporte entra al inicio del mes
                    invested += contrib
                    peak = max(peak, eq)
                    r = monthly[(s + j) % n] * lev - max(0.0, lev - 1) * borrow_rate / 12
                    eq = eq * (1 + r) if r > -1 else 0.0
                    if eq <= 0.02 * invested:
                        dead = True
                        eq = 0.0
                        break
                    if eq < 0.5 * peak:
                        dd50 = True
                    if eq < 0.9 * invested:
                        below = True
                    peak = max(peak, eq)
                    m += 1
                    if reached is None and eq >= target:
                        reached = m
                if dead:
                    break
            if dead:
                ruined += 1
            if dd50:
                deep_dd += 1
            if below:
                underwater += 1
            if eq < invested:
                end_loss += 1
            if reached is not None:
                hit_months.append(reached)
            finals.append(eq)
        hit_months.sort()
        finals.sort()

        def p_by(years):
            return round(100.0 * sum(1 for x in hit_months if x <= years * 12) / sims, 1)

        out.append({
            "leverage": lev,
            "median_years_to_target": round(hit_months[len(hit_months) // 2] / 12, 1)
            if len(hit_months) * 2 >= sims else None,
            "prob_target_10y_pct": p_by(10), "prob_target_20y_pct": p_by(20),
            "prob_target_ever_pct": round(100.0 * len(hit_months) / sims, 1),
            "prob_ruin_pct": round(100.0 * ruined / sims, 1),
            "prob_drop_50pct": round(100.0 * deep_dd / sims, 1),
            "prob_ever_10pct_below_contributed_pct": round(100.0 * underwater / sims, 1),
            "prob_end_below_contributed_pct": round(100.0 * end_loss / sims, 1),
            "final_p10": round(finals[int(0.10 * sims)]), "final_median": round(finals[sims // 2]),
            "final_p90": round(finals[int(0.90 * sims)]),
        })
    return {"months_of_history": n, "simulations": sims, "capital": capital, "monthly_contribution": contrib,
            "target": target, "horizon_years": max_years, "borrow_rate": borrow_rate, "results": out,
            "warning": ("Proyección basada en la historia remuestreada, no una promesa. Con datos mensuales se "
                        "subestiman las caídas DENTRO del mes, que con apalancamiento pueden liquidarte antes.")}
