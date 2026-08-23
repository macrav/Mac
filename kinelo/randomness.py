"""
Batería de tests de aleatoriedad para los sorteos de KINELO.

La pregunta que responde este módulo es una sola: ¿hay en el histórico alguna
estructura que un modelo pueda explotar? Si el RNG es correcto, todos estos
tests deben dar p-valores repartidos uniformemente entre 0 y 1, y ninguno
debe sobrevivir la corrección por comparaciones múltiples.

Cada test devuelve un dict con el estadístico, los grados de libertad, el
p-valor y una lectura en castellano.
"""

from __future__ import annotations

from collections import Counter
from math import comb, sqrt

from paytable import DRAWN, POOL_SIZE
from stats_util import benjamini_hochberg, chi2_sf, two_sided_normal_p

# Probabilidad de que un número cualquiera salga en un sorteo dado: 20/80
P_NUMBER = DRAWN / POOL_SIZE


def _verdict(p: float, alpha: float = 0.05) -> str:
    if p < 0.001:
        return "DESVÍA FUERTE del azar (p < 0.001)"
    if p < alpha:
        return f"desvía del azar (p = {p:.4f})"
    return f"compatible con azar puro (p = {p:.4f})"


def test_uniform_frequencies(draws: list[list[int]]) -> dict:
    """
    Chi-cuadrado sobre la frecuencia de cada número.

    Si el RNG es justo, cada número sale en 1 de cada 4 sorteos.
    Es el test que refuta la idea de "números calientes y fríos".
    """
    n = len(draws)
    counts = Counter()
    for d in draws:
        counts.update(d)
    expected = n * P_NUMBER
    if expected < 5:
        return {"test": "uniformidad_frecuencias", "error":
                f"muy pocos sorteos ({n}); se necesitan >= 20 para este test"}
    stat = sum((counts.get(i, 0) - expected) ** 2 / expected
               for i in range(1, POOL_SIZE + 1))
    df = POOL_SIZE - 1
    p = chi2_sf(stat, df)
    return {
        "test": "uniformidad_frecuencias",
        "descripcion": "¿Salen los 80 números con la misma frecuencia?",
        "chi2": stat, "df": df, "p": p,
        "n_sorteos": n,
        "esperado_por_numero": expected,
        "min_observado": min(counts.get(i, 0) for i in range(1, POOL_SIZE + 1)),
        "max_observado": max(counts.get(i, 0) for i in range(1, POOL_SIZE + 1)),
        "veredicto": _verdict(p),
    }


def test_per_number(draws: list[list[int]], alpha: float = 0.05) -> dict:
    """
    Un test binomial por cada número, con corrección FDR (Benjamini-Hochberg).

    Sin la corrección, con 80 tests al 5% salen ~4 "números calientes" falsos
    en cualquier histórico aleatorio. Con la corrección, no sobrevive ninguno.
    """
    n = len(draws)
    counts = Counter()
    for d in draws:
        counts.update(d)
    mu = n * P_NUMBER
    sigma = sqrt(n * P_NUMBER * (1 - P_NUMBER))
    rows = []
    for num in range(1, POOL_SIZE + 1):
        obs = counts.get(num, 0)
        z = (obs - mu) / sigma if sigma else 0.0
        rows.append({"numero": num, "veces": obs, "z": z,
                     "p": two_sided_normal_p(z)})
    flags = benjamini_hochberg([r["p"] for r in rows], alpha)
    for r, f in zip(rows, flags):
        r["significativo_fdr"] = f
    naive = sum(1 for r in rows if r["p"] < alpha)
    survivors = [r["numero"] for r in rows if r["significativo_fdr"]]
    return {
        "test": "por_numero_fdr",
        "descripcion": "¿Algún número individual sale más de lo que debería?",
        "n_sorteos": n,
        "significativos_sin_correccion": naive,
        "esperados_por_azar_sin_correccion": round(POOL_SIZE * alpha, 1),
        "significativos_con_fdr": survivors,
        "detalle": rows,
        "veredicto": (
            "ningún número sobrevive la corrección por comparaciones múltiples: "
            "no hay números calientes"
            if not survivors
            else f"sobreviven {len(survivors)} números: {survivors}"
        ),
    }


def test_consecutive_overlap(draws: list[list[int]]) -> dict:
    """
    Solapamiento entre sorteos consecutivos.

    Cuántos números repite el sorteo t+1 respecto del t. Bajo independencia
    sigue una hipergeométrica de media 5 (20*20/80). Si el RNG arrastrara
    estado, este test lo delataría.
    """
    if len(draws) < 2:
        return {"test": "solapamiento_consecutivo", "error": "hacen falta >= 2 sorteos"}
    obs = Counter()
    sets = [set(d) for d in draws]
    for a, b in zip(sets, sets[1:]):
        obs[len(a & b)] += 1
    trials = len(draws) - 1
    total = comb(POOL_SIZE, DRAWN)
    probs = {k: comb(DRAWN, k) * comb(POOL_SIZE - DRAWN, DRAWN - k) / total
             for k in range(DRAWN + 1)}
    # Agrupamos las colas para que toda celda tenga esperado >= 5.
    bins, cur_k, cur_p, cur_o = [], [], 0.0, 0
    for k in range(DRAWN + 1):
        cur_k.append(k); cur_p += probs[k]; cur_o += obs.get(k, 0)
        if cur_p * trials >= 5:
            bins.append((tuple(cur_k), cur_p, cur_o)); cur_k, cur_p, cur_o = [], 0.0, 0
    if cur_k:
        if bins:
            ks, p0, o0 = bins[-1]
            bins[-1] = (ks + tuple(cur_k), p0 + cur_p, o0 + cur_o)
        else:
            bins.append((tuple(cur_k), cur_p, cur_o))
    if len(bins) < 2:
        return {"test": "solapamiento_consecutivo",
                "error": f"muy pocos sorteos ({len(draws)}) para agrupar celdas"}
    stat = sum((o - p * trials) ** 2 / (p * trials) for _, p, o in bins)
    df = len(bins) - 1
    pv = chi2_sf(stat, df)
    mean_obs = sum(k * c for k, c in obs.items()) / trials
    return {
        "test": "solapamiento_consecutivo",
        "descripcion": "¿El sorteo anterior influye en el siguiente?",
        "chi2": stat, "df": df, "p": pv,
        "media_observada": mean_obs,
        "media_teorica": DRAWN * DRAWN / POOL_SIZE,
        "veredicto": _verdict(pv),
    }


def test_lag1_autocorrelation(draws: list[list[int]], alpha: float = 0.05) -> dict:
    """
    Autocorrelación de retardo 1, número por número.

    Si un número salió en el sorteo t, ¿cambia su probabilidad en t+1?
    Es la base de toda estrategia de "seguir la racha". Con FDR encima.
    """
    if len(draws) < 30:
        return {"test": "autocorrelacion_lag1",
                "error": f"muy pocos sorteos ({len(draws)}); se necesitan >= 30"}
    sets = [set(d) for d in draws]
    rows = []
    for num in range(1, POOL_SIZE + 1):
        series = [1 if num in s else 0 for s in sets]
        a = series[:-1]
        b = series[1:]
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        num_ = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
        r = num_ / den if den else 0.0
        z = r * sqrt(n - 1)
        rows.append({"numero": num, "r": r, "z": z, "p": two_sided_normal_p(z)})
    flags = benjamini_hochberg([r["p"] for r in rows], alpha)
    for r, f in zip(rows, flags):
        r["significativo_fdr"] = f
    survivors = [r["numero"] for r in rows if r["significativo_fdr"]]
    max_abs_r = max(abs(r["r"]) for r in rows)
    return {
        "test": "autocorrelacion_lag1",
        "descripcion": "¿Que un número haya salido predice que vuelva a salir?",
        "correlacion_absoluta_maxima": max_abs_r,
        "significativos_con_fdr": survivors,
        "detalle": rows,
        "veredicto": (
            "ninguna autocorrelación sobrevive el FDR: el pasado no predice el futuro"
            if not survivors else f"sobreviven {len(survivors)} números: {survivors}"
        ),
    }


def test_gaps(draws: list[list[int]]) -> dict:
    """
    Test de huecos: cuántos sorteos pasan entre dos apariciones de un número.

    Bajo azar la distribución es geométrica con p = 1/4. Es el test que refuta
    "este número ya está atrasado, le toca salir".
    """
    if len(draws) < 50:
        return {"test": "huecos", "error":
                f"muy pocos sorteos ({len(draws)}); se necesitan >= 50"}
    sets = [set(d) for d in draws]
    gaps = Counter()
    last = {}
    for i, s in enumerate(sets):
        for num in s:
            if num in last:
                gaps[i - last[num]] += 1
            last[num] = i
    total = sum(gaps.values())
    p = P_NUMBER
    bins, cur_g, cur_p, cur_o = [], [], 0.0, 0
    g = 1
    while cur_p < 0.999 and g < 200:
        pk = (1 - p) ** (g - 1) * p
        cur_g.append(g); cur_p += pk; cur_o += gaps.get(g, 0)
        if cur_p * total >= 5 and len(cur_g) >= 1:
            bins.append((tuple(cur_g), cur_p, cur_o)); cur_g, cur_p, cur_o = [], 0.0, 0
        g += 1
    tail_p = max(0.0, 1.0 - sum(b[1] for b in bins))
    tail_o = total - sum(b[2] for b in bins)
    if tail_p * total >= 5:
        bins.append((("cola",), tail_p, tail_o))
    elif bins:
        ks, p0, o0 = bins[-1]
        bins[-1] = (ks + ("cola",), p0 + tail_p, o0 + tail_o)
    stat = sum((o - pp * total) ** 2 / (pp * total) for _, pp, o in bins if pp > 0)
    df = len(bins) - 1
    pv = chi2_sf(stat, df)
    mean_gap = sum(k * v for k, v in gaps.items()) / total
    return {
        "test": "huecos",
        "descripcion": "¿Un número 'atrasado' tiene más chance de salir?",
        "chi2": stat, "df": df, "p": pv,
        "hueco_medio_observado": mean_gap,
        "hueco_medio_teorico": 1 / p,
        "veredicto": _verdict(pv),
    }


def test_sum_distribution(draws: list[list[int]]) -> dict:
    """
    Suma de los 20 números de cada sorteo.

    Media teórica 810, desviación teórica ~ 91.4. Detecta sesgos globales que
    los tests de frecuencia individual no ven.
    """
    n = len(draws)
    if n < 30:
        return {"test": "suma", "error": f"muy pocos sorteos ({n})"}
    sums = [sum(d) for d in draws]
    mean_obs = sum(sums) / n
    mu = DRAWN * (POOL_SIZE + 1) / 2
    var = DRAWN * (POOL_SIZE - DRAWN) * (POOL_SIZE + 1) / 12
    sd = sqrt(var)
    z = (mean_obs - mu) / (sd / sqrt(n))
    pv = two_sided_normal_p(z)
    return {
        "test": "suma",
        "descripcion": "¿La suma de cada sorteo se comporta como debería?",
        "media_observada": mean_obs, "media_teorica": mu,
        "desv_teorica": sd, "z": z, "p": pv,
        "veredicto": _verdict(pv),
    }


def run_all(draws: list[list[int]]) -> list[dict]:
    """Corre la batería completa."""
    return [
        test_uniform_frequencies(draws),
        test_per_number(draws),
        test_consecutive_overlap(draws),
        test_lag1_autocorrelation(draws),
        test_gaps(draws),
        test_sum_distribution(draws),
    ]
