#!/usr/bin/env python3
"""
Pruebas del sistema. Sin dependencias: python3 test_kinelo.py

Se verifica sobre todo que la matemática exacta coincida con la simulación,
que es la única forma seria de confiar en fórmulas cerradas.
"""

from __future__ import annotations

import random
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import db
from kinelo_math import expected_return, hit_probability, variance_of_return
from paytable import DRAWN, PAYOUT, POOL_SIZE, payout_for
from portfolio import compare_overlap_designs, portfolio_stats, prob_portfolio_returns_nothing
from randomness import run_all, test_per_number, test_uniform_frequencies
from simulate import biased_draws, fair_draws
from stats_util import benjamini_hochberg, chi2_sf
from tickets import best_bet_type, generate_portfolio

FAILED: list[str] = []


def check(cond: bool, label: str) -> None:
    print(f"  {'ok  ' if cond else 'FALLA'}  {label}")
    if not cond:
        FAILED.append(label)


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def test_probabilities_sum_to_one():
    print("\nDistribución hipergeométrica")
    for t in PAYOUT:
        total = sum(hit_probability(t, k) for k in range(t + 1))
        check(total == Fraction(1), f"las probabilidades del tipo {t} suman exactamente 1")


def test_known_values():
    print("\nValores contra cálculo independiente")
    # P(1 acierto | marco 1 número) = 20/80 = 1/4
    check(hit_probability(1, 1) == Fraction(1, 4), "P(acertar con 1 número) = 1/4")
    # Tipo 1 paga 3x con probabilidad 1/4 -> RTP = 0.75 exacto
    check(expected_return(1) == Fraction(3, 4), "RTP del tipo 1 = 75% exacto")
    # P(10 de 10) = C(20,10)/C(80,10)
    from math import comb
    check(hit_probability(10, 10) == Fraction(comb(20, 10), comb(80, 10)),
          "P(10 de 10) coincide con C(20,10)/C(80,10)")


def test_rtp_matches_simulation():
    print("\nRTP exacto vs simulación (500,000 sorteos por tipo)")
    rng = random.Random(31337)
    pool = list(range(1, POOL_SIZE + 1))
    n = 500_000
    for t in (1, 2, 5):
        picks = set(rng.sample(pool, t))
        total = 0
        for _ in range(n):
            d = set(rng.sample(pool, DRAWN))
            total += payout_for(t, len(picks & d))
        sim = total / n
        exact = float(expected_return(t))
        sd = float(variance_of_return(t)) ** 0.5
        tol = 5 * sd / (n ** 0.5)
        check(approx(sim, exact, tol),
              f"tipo {t}: simulado {sim:.4f} vs exacto {exact:.4f} (±{tol:.4f})")


def test_bitmask_roundtrip():
    print("\nCodificación de sorteos en bitmask")
    rng = random.Random(7)
    ok = True
    for _ in range(500):
        nums = sorted(rng.sample(range(1, POOL_SIZE + 1), DRAWN))
        if db.from_bitmask(db.to_bitmask(nums)) != nums:
            ok = False
            break
    check(ok, "500 sorteos sobreviven ida y vuelta a bitmask")
    try:
        db.to_bitmask([1, 1, 2])
        check(False, "se rechaza un número repetido")
    except ValueError:
        check(True, "se rechaza un número repetido")
    try:
        db.validate_draw(list(range(1, 20)))
        check(False, "se rechaza un sorteo con 19 números")
    except ValueError:
        check(True, "se rechaza un sorteo con 19 números")


def test_db_roundtrip():
    print("\nBase de datos")
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "t.db")
        draws = fair_draws(300, seed=5)
        rows = [(i + 1, f"2026-01-01T{i//60:02d}:{i%60:02d}:00", d)
                for i, d in enumerate(draws)]
        ins, skip = db.insert_draws(conn, rows, "test")
        check(ins == 300 and skip == 0, "se insertan 300 sorteos")
        ins2, skip2 = db.insert_draws(conn, rows, "test")
        check(ins2 == 0 and skip2 == 300, "re-insertar los mismos no duplica")
        db.rebuild_frequencies(conn)
        total = conn.execute("SELECT SUM(times_drawn) s FROM number_stats").fetchone()["s"]
        check(total == 300 * DRAWN, "las frecuencias suman 300 x 20")
        check(db.load_matrix(conn) == [sorted(d) for d in draws],
              "los sorteos se recuperan idénticos")


def test_randomness_null():
    print("\nTests de aleatoriedad — control negativo (RNG limpio)")
    draws = fair_draws(20_000, seed=11)
    for r in run_all(draws):
        if "error" in r:
            continue
        if "p" in r:
            check(r["p"] > 0.001, f"{r['test']}: no marca falso positivo (p={r['p']:.3f})")
        else:
            check(not r.get("significativos_con_fdr"),
                  f"{r['test']}: no marca falso positivo")


def test_randomness_power():
    print("\nTests de aleatoriedad — control positivo (sesgo inyectado)")
    hot = {7: 1.15, 23: 1.15, 41: 1.15, 58: 1.15, 72: 1.15}
    draws = biased_draws(8_000, hot, seed=3)
    u = test_uniform_frequencies(draws)
    check(u["p"] < 0.001, f"chi2 detecta un sesgo de +15% (p={u['p']:.2e})")
    pn = test_per_number(draws)
    found = set(pn["significativos_con_fdr"])
    check(set(hot) <= found, f"el FDR identifica los 5 números sesgados: {sorted(found)}")


def test_bh_correction():
    print("\nCorrección de Benjamini-Hochberg")
    check(not any(benjamini_hochberg([0.5] * 80)), "80 p-valores de 0.5: no rechaza ninguno")
    flags = benjamini_hochberg([1e-9] + [0.9] * 79)
    check(flags[0] and sum(flags) == 1, "un p-valor diminuto entre 80: rechaza solo ese")
    check(chi2_sf(0, 5) == 1.0, "chi2_sf(0, df) = 1")


def test_portfolio_expected_value_invariant():
    print("\nCartera: el retorno esperado no depende del solapamiento")
    rows = compare_overlap_designs(5, 4)
    vals = [r["retorno_esperado_soles"] for r in rows]
    check(max(vals) - min(vals) < 1e-9,
          f"seis diseños, mismo retorno esperado ({vals[0]:.6f})")
    sds = [r["desv_estandar_soles"] for r in rows]
    check(sds == sorted(sds),
          "la desviación estándar crece monótonamente con el solapamiento")
    check(sds[-1] > 1.9 * sds[0],
          f"tickets iguales duplican la volatilidad ({sds[0]:.1f} -> {sds[-1]:.1f})")


def test_portfolio_matches_simulation():
    print("\nCartera: exacto vs simulación (300,000 sorteos)")
    rng = random.Random(999)
    pool = list(range(1, POOL_SIZE + 1))
    designs = {
        "disjunta": [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15], [16, 17, 18, 19, 20]],
        "solape 3": [[1, 2, 3, 4, 5], [1, 2, 3, 6, 7], [1, 2, 3, 8, 9], [1, 2, 3, 10, 11]],
    }
    n = 300_000
    for name, tk in designs.items():
        st = portfolio_stats(tk, 5)
        sets = [set(t) for t in tk]
        tot = tot2 = 0.0
        zero = 0
        for _ in range(n):
            d = set(rng.sample(pool, DRAWN))
            v = sum(payout_for(5, len(s & d)) for s in sets)
            tot += v
            tot2 += v * v
            if v == 0:
                zero += 1
        m = tot / n
        sd = (tot2 / n - m * m) ** 0.5
        check(approx(m, st["retorno_esperado_soles"], 6 * sd / (n ** 0.5)),
              f"{name}: retorno simulado {m:.4f} vs exacto {st['retorno_esperado_soles']:.4f}")
        check(approx(sd, st["desv_estandar_soles"], 0.10 * st["desv_estandar_soles"]),
              f"{name}: desv. simulada {sd:.2f} vs exacta {st['desv_estandar_soles']:.2f}")
        if name == "disjunta":
            exact_zero = prob_portfolio_returns_nothing(tk, 5)
            check(approx(zero / n, exact_zero, 0.005),
                  f"{name}: P(cero) simulada {zero/n:.4f} vs exacta {exact_zero:.4f}")


def test_tickets():
    print("\nGenerador de tickets")
    check(best_bet_type() == 5, "el tipo de mayor RTP es el 5")
    res = generate_portfolio(4, None, seed=20260823)
    tk = res["tickets"]
    check(len(tk) == 4, "genera 4 tickets")
    check(all(len(set(t)) == 5 for t in tk), "cada ticket tiene 5 números distintos")
    flat = [n for t in tk for n in t]
    check(len(set(flat)) == 20, "los 20 números son todos distintos entre tickets")
    check(all(1 <= n <= 80 for n in flat), "todos los números están en 1..80")
    check(res["stats"]["solapamiento_total"] == 0, "solapamiento total = 0")
    check(generate_portfolio(4, None, 20260823)["tickets"] == tk,
          "la misma semilla reproduce los mismos tickets")
    try:
        generate_portfolio(20, 5)
        check(False, "rechaza pedir más números de los que existen")
    except ValueError:
        check(True, "rechaza pedir más números de los que existen")


def main() -> int:
    print("=" * 66)
    print("PRUEBAS DEL SISTEMA KINELO")
    print("=" * 66)
    for fn in (
        test_probabilities_sum_to_one,
        test_known_values,
        test_bitmask_roundtrip,
        test_db_roundtrip,
        test_bh_correction,
        test_portfolio_expected_value_invariant,
        test_tickets,
        test_randomness_null,
        test_randomness_power,
        test_rtp_matches_simulation,
        test_portfolio_matches_simulation,
    ):
        fn()
    print("\n" + "=" * 66)
    if FAILED:
        print(f"FALLARON {len(FAILED)} comprobaciones:")
        for f in FAILED:
            print("  -", f)
        return 1
    print("TODAS LAS COMPROBACIONES PASARON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
