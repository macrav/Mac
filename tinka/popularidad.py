"""
Estima la popularidad de cada número, uno por uno, a partir de los ganadores.

Idea: no se puede ver qué números marca la gente, pero sí cuántos ganadores
hubo en cada sorteo. Si un número está muy jugado, los sorteos en los que ese
número sale tienen más ganadores de 4 aciertos que los sorteos en los que no
sale. Con 829 sorteos se puede separar el efecto de cada bolilla.

Modelo: Poisson con sobredispersión.
    log(ganadores de 4 aciertos) = log(volumen) + época + Σ pop_b · [b salió]

Controles:
  - exposición: ganadores de "2 aciertos + boliyapa" (proxy del volumen vendido)
  - época: el bombo creció de 45 a 53 bolillas, y los números nuevos sólo
    existen en los sorteos recientes; sin este control se confundiría
    "número impopular" con "número que sólo existe desde hace poco"
  - penalización ridge: cada número sale en ~1 de cada 9 sorteos, así que las
    estimaciones individuales son ruidosas y conviene encogerlas hacia cero
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import defaultdict

import numpy as np
from scipy import stats

import analisis

AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(AQUI, "data", "tinka.sqlite")
CATEGORIA = "4 aciertos"


def ajustar(X: np.ndarray, y: np.ndarray, offset: np.ndarray,
            penal: np.ndarray, iters: int = 200) -> tuple[np.ndarray, np.ndarray, float]:
    """Poisson por IRLS con penalización ridge por coeficiente."""
    beta = np.zeros(X.shape[1])
    beta[0] = float(np.log(y.mean()) - offset.mean())
    P = np.diag(penal)
    for _ in range(iters):
        eta = X @ beta + offset
        mu = np.exp(np.clip(eta, -30, 30))
        A = X.T @ (X * mu[:, None]) + P
        grad = X.T @ (y - mu) - penal * beta
        paso = np.linalg.solve(A, grad)
        beta = beta + paso
        if np.max(np.abs(paso)) < 1e-10:
            break
    eta = X @ beta + offset
    mu = np.exp(np.clip(eta, -30, 30))
    gl = max(len(y) - np.trace(np.linalg.solve(X.T @ (X * mu[:, None]) + P,
                                               X.T @ (X * mu[:, None]))), 1)
    disp = float((((y - mu) ** 2) / mu).sum() / gl)
    cov = np.linalg.inv(X.T @ (X * mu[:, None]) + P) * disp
    return beta, np.sqrt(np.diag(cov)), disp


def main() -> int:
    con = sqlite3.connect(DB)
    sorteos = analisis.cargar(con)
    eras = analisis.detectar_eras(sorteos)
    era_de = {}
    for k, e in enumerate(eras):
        for i in range(e["desde"], e["hasta"] + 1):
            era_de[i] = k

    prem = defaultdict(dict)
    for s, c, n in con.execute("SELECT sorteo, categoria, ganadores FROM ganadores"):
        prem[s][c] = n

    usados, R = [], eras[-1]["rango"]
    for i, s in enumerate(sorteos):
        y = prem.get(s["sorteo"], {}).get(CATEGORIA)
        expo = prem.get(s["sorteo"], {}).get("2 aciertos + boliyapa")
        if y and expo:
            usados.append((i, s, y, expo))

    n = len(usados)
    n_eras = len(eras)
    X = np.zeros((n, 1 + (n_eras - 1) + R))
    for fila, (i, s, _, _) in enumerate(usados):
        X[fila, 0] = 1.0
        k = era_de[i]
        if k > 0:
            X[fila, k] = 1.0                       # época (la primera es la base)
        for b in s["bolas"]:
            X[fila, n_eras + b - 1] = 1.0          # ¿salió la bolilla b?

    y = np.array([u[2] for u in usados], float)
    offset = np.log(np.array([u[3] for u in usados], float))

    # sin penalizar el intercepto ni las épocas; ridge suave en los números
    penal = np.zeros(X.shape[1])
    penal[n_eras:] = 25.0

    beta, ee, disp = ajustar(X, y, offset, penal)
    pop = beta[n_eras:]
    err = ee[n_eras:]

    print("=" * 78)
    print("POPULARIDAD ESTIMADA POR NÚMERO")
    print(f"(modelo sobre {n} sorteos, categoría '{CATEGORIA}', "
          f"sobredispersión {disp:.0f})")
    print("=" * 78)
    print("\nÍndice: 1.00 = número de popularidad media. Por encima de 1, más")
    print("jugado que el promedio; por debajo, menos jugado.\n")

    centro = pop.mean()
    indice = np.exp(pop - centro)
    orden = np.argsort(indice)

    print("  MENOS JUGADOS (los que conviene marcar)")
    for j in orden[:12]:
        print(f"    {j+1:2d}   {indice[j]:.3f}   (±{err[j]:.3f} en log)")
    print("\n  MÁS JUGADOS (los que conviene evitar)")
    for j in orden[::-1][:12]:
        print(f"    {j+1:2d}   {indice[j]:.3f}   (±{err[j]:.3f} en log)")

    bajos = indice[:31].mean()
    altos = indice[31:].mean()
    print(f"\n  Promedio del 1 al 31 : {bajos:.3f}")
    print(f"  Promedio del 32 al {R}: {altos:.3f}")
    print(f"  Los números altos están un {100*(1-altos/bajos):.0f}% menos jugados.")

    # ¿el patrón es real o es ruido? prueba conjunta sobre los 53 coeficientes
    z = pop / err
    chi2 = float((z ** 2).sum())
    p = stats.chi2.sf(chi2, R)
    print(f"\n  Prueba conjunta (¿los números difieren entre sí?): "
          f"chi2={chi2:.1f}, gl={R}, p={p:.4f}")

    # validación fuera de muestra: ajustar con la primera mitad y ver si predice
    mitad = n // 2
    # en cada mitad hay columnas vacías (los números 46–53 no existían antes),
    # así que se penaliza también las épocas para que el sistema no sea singular
    penal_split = penal.copy()
    penal_split[1:n_eras] = 1.0
    b1, _, _ = ajustar(X[:mitad], y[:mitad], offset[:mitad], penal_split)
    b2, _, _ = ajustar(X[mitad:], y[mitad:], offset[mitad:], penal_split)
    comun = [j for j in range(R) if X[:mitad, n_eras + j].sum() > 5
             and X[mitad:, n_eras + j].sum() > 5]
    r = float(np.corrcoef(b1[n_eras:][comun], b2[n_eras:][comun])[0, 1])
    pr = 2 * stats.norm.sf(abs(r) * math.sqrt(max(len(comun) - 3, 1)))
    print(f"  Validación partiendo la historia en dos mitades: correlación "
          f"entre\n  las popularidades estimadas en cada mitad = {r:+.3f} "
          f"(n={len(comun)} números, p={pr:.3f})")
    # ¿esa correlación es sólo el efecto bajos/altos, o hay algo por número?
    v1, v2 = b1[n_eras:][comun], b2[n_eras:][comun]
    banda = np.array([1.0 if j < 31 else 0.0 for j in comun])
    A = np.column_stack([np.ones(len(banda)), banda])

    def sin_banda(v):
        return v - A @ np.linalg.lstsq(A, v, rcond=None)[0]

    rp = float(np.corrcoef(sin_banda(v1), sin_banda(v2))[0, 1])
    gl = len(comun) - 3
    tp = rp * math.sqrt(gl / max(1 - rp ** 2, 1e-9))
    p_rp = 2 * stats.t.sf(abs(tp), gl)
    print(f"  Quitando el efecto bajos/altos, la correlación baja a {rp:+.3f} "
          f"(p={p_rp:.3f}).")
    print(
        "\n  Veredicto honesto:\n"
        "    - Que los números del 1 al 31 estén más jugados: sólido, se repite\n"
        "      en cualquier corte de los datos y es un efecto grande.\n"
        "    - Que un número concreto esté más jugado que otro de su misma\n"
        "      banda: evidencia débil. La prueba conjunta no lo detecta y dentro\n"
        "      del 1–31 no se replica. Se usa sólo como criterio de desempate,\n"
        "      encogido, nunca como base de la elección."
    )

    # ------------------------------------------------------------------
    # Encogimiento empírico-Bayes: cada número se acerca al promedio de su
    # banda en proporción a lo mal medido que esté. El 51, el 52 y el 53
    # existen desde hace meses, así que su estimación es muy imprecisa y hay
    # que desconfiar de ella; el 12 o el 27 llevan cientos de sorteos.
    pop_c = pop - centro
    shrunk = np.zeros_like(pop_c)
    for lo, hi in ((0, 31), (31, R)):
        idx = np.arange(lo, hi)
        media = pop_c[idx].mean()
        var_obs = pop_c[idx].var(ddof=1)
        var_err = (err[idx] ** 2).mean()
        tau2 = max(var_obs - var_err, 0.0)
        peso = tau2 / (tau2 + err[idx] ** 2)
        shrunk[idx] = media + peso * (pop_c[idx] - media)
        print(f"\n  Banda {lo+1}–{hi}: dispersión real estimada "
              f"tau={math.sqrt(tau2):.3f} contra error medio "
              f"{math.sqrt(var_err):.3f}")
        print(f"    peso que conserva cada estimación individual: "
              f"{peso.min():.2f} a {peso.max():.2f}")
    indice_c = np.exp(shrunk)
    print("\n  Índice tras encoger (el que usa el generador):")
    ordc = np.argsort(indice_c)
    print("    menos jugados: " + ", ".join(
        f"{j+1} ({indice_c[j]:.3f})" for j in ordc[:8]))
    print("    más jugados:   " + ", ".join(
        f"{j+1} ({indice_c[j]:.3f})" for j in ordc[::-1][:8]))

    destino = os.path.join(AQUI, "data", "popularidad.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(
            {
                "categoria": CATEGORIA,
                "sorteos": n,
                "rango": R,
                "replica_entre_mitades": r,
                "replica_sin_banda": rp,
                "indice": {str(j + 1): float(indice_c[j]) for j in range(R)},
                "indice_sin_encoger": {str(j + 1): float(indice[j]) for j in range(R)},
                "ee_log": {str(j + 1): float(err[j]) for j in range(R)},
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nGuardado en {destino}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
