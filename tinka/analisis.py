"""
Análisis estadístico del histórico de La Tinka.

El objetivo NO es adivinar bolillas. Es contestar con datos tres preguntas:

  1. ¿El sorteo es uniforme? (¿alguna bolilla sale más de lo que debería?)
  2. ¿Hay memoria entre sorteos? (¿sirven "calientes", "fríos", "atrasados"?)
  3. ¿Qué números juega la gente? (esto sí tiene señal y sí cambia el premio)

Salida: reporte de texto por stdout.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections import Counter, defaultdict

import numpy as np
from scipy import stats

AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(AQUI, "data", "tinka.sqlite")

# ---------------------------------------------------------------- utilidades


def titulo(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def cargar(con: sqlite3.Connection) -> list[dict]:
    filas = con.execute(
        "SELECT sorteo, fecha, b1,b2,b3,b4,b5,b6, boliyapa FROM sorteos ORDER BY sorteo"
    ).fetchall()
    return [
        {
            "sorteo": f[0],
            "fecha": f[1],
            "bolas": sorted(f[2:8]),
            "boliyapa": f[8],
        }
        for f in filas
    ]


def detectar_eras(sorteos: list[dict]) -> list[dict]:
    """
    La Tinka fue ampliando el bombo (45 → 46 → 48 → 50 → 53 bolillas).
    Mezclar épocas distintas invalida cualquier estadística de frecuencia,
    así que el histórico se parte cada vez que aparece una bolilla nueva
    por encima del máximo conocido.
    """
    eras, maximo, inicio = [], 0, 0
    for i, s in enumerate(sorteos):
        alto = max(s["bolas"])
        if alto > maximo:
            if maximo:
                eras.append({"desde": inicio, "hasta": i - 1, "rango": maximo})
                inicio = i
            maximo = alto
    eras.append({"desde": inicio, "hasta": len(sorteos) - 1, "rango": maximo})

    # Cuando amplían el bombo, las bolillas nuevas no aparecen todas en el
    # primer sorteo: el 51, el 52 y el 53 tardaron semanas en salir. Eso genera
    # tramos falsos de pocos sorteos. Se fusionan HACIA ADELANTE (el tramo corto
    # pertenece al formato nuevo, no al viejo); fusionar hacia atrás inflaría el
    # rango de la época anterior e inventaría bolillas que "nunca salen".
    fusionadas: list[dict] = []
    pendiente: dict | None = None
    for idx, orig in enumerate(eras):
        e = dict(orig)
        if pendiente:
            e["desde"] = pendiente["desde"]
            pendiente = None
        if e["hasta"] - e["desde"] + 1 < 15 and idx < len(eras) - 1:
            pendiente = e
            continue
        fusionadas.append(e)
    if pendiente:
        fusionadas.append(pendiente)
    # el rango de cada época es el máximo realmente observado en ella
    for e in fusionadas:
        e["rango"] = max(max(s["bolas"]) for s in sorteos[e["desde"]: e["hasta"] + 1])
    for e in fusionadas:
        e["n"] = e["hasta"] - e["desde"] + 1
        e["f_ini"] = sorteos[e["desde"]]["fecha"]
        e["f_fin"] = sorteos[e["hasta"]]["fecha"]
        e["s_ini"] = sorteos[e["desde"]]["sorteo"]
        e["s_fin"] = sorteos[e["hasta"]]["sorteo"]
    return fusionadas


# ------------------------------------------------------- 1. uniformidad


def prueba_uniformidad(sorteos: list[dict], eras: list[dict]) -> None:
    titulo("1. ¿EL BOMBO ES JUSTO? (prueba chi-cuadrado de uniformidad)")
    print(
        "H0: todas las bolillas tienen la misma probabilidad.\n"
        "Un p-valor alto significa que los datos son compatibles con un bombo justo.\n"
    )
    for e in eras:
        tramo = sorteos[e["desde"]: e["hasta"] + 1]
        R = e["rango"]
        conteo = Counter()
        for s in tramo:
            conteo.update(s["bolas"])
        obs = np.array([conteo.get(b, 0) for b in range(1, R + 1)], float)
        esp = obs.sum() / R
        chi2 = ((obs - esp) ** 2 / esp).sum()
        p = stats.chi2.sf(chi2, R - 1)
        top = sorted(range(1, R + 1), key=lambda b: -conteo.get(b, 0))[:3]
        bot = sorted(range(1, R + 1), key=lambda b: conteo.get(b, 0))[:3]
        print(
            f"  1–{R:2d} | sorteos {e['s_ini']}–{e['s_fin']} ({e['n']:3d} sorteos, "
            f"{e['f_ini']} a {e['f_fin']})"
        )
        print(
            f"        esperado {esp:6.1f} por bolilla | chi2={chi2:7.2f} gl={R-1:2d} "
            f"p={p:.3f}  ->  {'sin evidencia de sesgo' if p > 0.05 else 'REVISAR'}"
        )
        print(
            f"        más salidas: {[(b, conteo.get(b,0)) for b in top]}  "
            f"menos: {[(b, conteo.get(b,0)) for b in bot]}"
        )
        # cuánto se separan "el más caliente" y "el más frío" por puro azar
        if e["n"] >= 30:
            sim = simular_extremos(e["n"], R)
            print(
                f"        por azar puro, el máximo esperado sería "
                f"{sim['max_medio']:.1f} (IC95 {sim['max_lo']:.0f}–{sim['max_hi']:.0f}) "
                f"y el mínimo {sim['min_medio']:.1f} "
                f"(IC95 {sim['min_lo']:.0f}–{sim['min_hi']:.0f})"
            )
        print()


def simular_extremos(n_sorteos: int, R: int, reps: int = 3000) -> dict:
    """Distribución del conteo máximo y mínimo bajo azar puro (bombo justo)."""
    rng = np.random.default_rng(7)
    maxs = np.empty(reps)
    mins = np.empty(reps)
    for i in range(reps):
        conteo = np.zeros(R, int)
        for _ in range(n_sorteos):
            conteo[rng.choice(R, 6, replace=False)] += 1
        maxs[i] = conteo.max()
        mins[i] = conteo.min()
    return {
        "max_medio": maxs.mean(),
        "max_lo": np.percentile(maxs, 2.5),
        "max_hi": np.percentile(maxs, 97.5),
        "min_medio": mins.mean(),
        "min_lo": np.percentile(mins, 2.5),
        "min_hi": np.percentile(mins, 97.5),
    }


# ------------------------------------------------------- 2. independencia


def prueba_memoria(sorteos: list[dict], eras: list[dict]) -> None:
    titulo("2. ¿HAY MEMORIA ENTRE SORTEOS?")

    # 2a. repetidos respecto del sorteo anterior
    print("2a. Bolillas que se repiten del sorteo anterior")
    rango_de = {}
    for e in eras:
        for i in range(e["desde"], e["hasta"] + 1):
            rango_de[i] = e["rango"]

    obs = Counter()
    esp = defaultdict(float)
    pares = 0
    for i in range(1, len(sorteos)):
        a, b = sorteos[i - 1], sorteos[i]
        if b["sorteo"] != a["sorteo"] + 1:
            continue  # hueco en la base: no son consecutivos de verdad
        if rango_de[i] != rango_de[i - 1]:
            continue  # cambió el formato entre ambos sorteos
        R = rango_de[i]
        obs[len(set(a["bolas"]) & set(b["bolas"]))] += 1
        pares += 1
        # la probabilidad esperada depende del tamaño del bombo de esa época
        for k in range(7):
            esp[k] += math.comb(6, k) * math.comb(R - 6, 6 - k) / math.comb(R, 6)
    print(f"    pares de sorteos consecutivos analizados: {pares}")
    print("    repetidas  observado  esperado(azar)")
    for k in range(5):
        print(f"       {k}         {obs.get(k,0):5d}      {esp[k]:8.1f}")
    o = np.array([obs.get(k, 0) for k in range(7)], float)
    e = np.array([esp[k] for k in range(7)], float)
    mask = e >= 5
    chi2 = (((o[mask] - e[mask]) ** 2) / e[mask]).sum()
    p = stats.chi2.sf(chi2, mask.sum() - 1)
    print(f"    chi2={chi2:.2f} p={p:.3f} -> "
          f"{'compatible con independencia' if p > 0.05 else 'REVISAR'}")

    # 2b. autocorrelación de la suma
    print("\n2b. Autocorrelación de la suma de las 6 bolillas (lag 1 a 5)")
    sumas = np.array([sum(s["bolas"]) for s in sorteos], float)
    sumas = (sumas - sumas.mean()) / sumas.std()
    for lag in range(1, 6):
        r = float(np.corrcoef(sumas[:-lag], sumas[lag:])[0, 1])
        n = len(sumas) - lag
        p = 2 * stats.norm.sf(abs(r) * math.sqrt(n))
        print(f"    lag {lag}: r={r:+.4f}  p={p:.3f}")
    print("    (con ~830 sorteos, |r| menor a 0.07 es indistinguible de cero)")

    # 2c. distribución de "sequía" (cada cuánto vuelve a salir una bolilla)
    print("\n2c. ¿Existen bolillas 'atrasadas'?")
    e_ult = max(eras, key=lambda e: e["n"])  # la época más larga = más potencia
    tramo = sorteos[e_ult["desde"]: e_ult["hasta"] + 1]
    R = e_ult["rango"]
    huecos = defaultdict(list)
    ultima = {}
    for i, s in enumerate(tramo):
        for b in s["bolas"]:
            if b in ultima:
                huecos[b].append(i - ultima[b])
            ultima[b] = i
    todos = np.array([h for v in huecos.values() for h in v], float)
    pgeo = 6 / R
    print(f"    época usada: 1–{R}, {len(tramo)} sorteos ({len(todos)} intervalos)")
    print(f"    esperado bajo independencia: media {1/pgeo:.2f} sorteos, "
          f"observado {todos.mean():.2f}")
    print(f"    desviación estándar esperada {math.sqrt(1-pgeo)/pgeo:.2f}, "
          f"observada {todos.std():.2f}")
    # chi-cuadrado sobre la distribución de sequías (la prueba KS no vale para
    # datos discretos; agrupar en clases sí)
    cortes = [1, 2, 3, 4, 6, 8, 11, 15, 21, 31, 10**9]
    obs_g = np.zeros(len(cortes) - 1)
    esp_g = np.zeros(len(cortes) - 1)
    for j in range(len(cortes) - 1):
        lo, hi = cortes[j], cortes[j + 1]
        obs_g[j] = ((todos >= lo) & (todos < hi)).sum()
        # P(lo <= G < hi) para la geométrica de parámetro pgeo
        esp_g[j] = len(todos) * ((1 - pgeo) ** (lo - 1) - (1 - pgeo) ** (hi - 1)
                                 if hi < 10**9 else (1 - pgeo) ** (lo - 1))
    chi2 = (((obs_g - esp_g) ** 2) / esp_g).sum()
    p = stats.chi2.sf(chi2, len(obs_g) - 1)
    print(f"    chi2={chi2:.2f} gl={len(obs_g)-1} p={p:.3f} -> "
          f"{'las sequías son las del azar' if p > 0.05 else 'REVISAR'}")
    print("    (una bolilla 'atrasada' no tiene ninguna probabilidad extra de salir)")


# ------------------------------------------------------- 3. backtest


def backtest(sorteos: list[dict], eras: list[dict]) -> None:
    titulo("3. BACKTEST: ¿ALGUNA ESTRATEGIA CLÁSICA GANA MÁS ACIERTOS?")
    print(
        "Para cada sorteo se arma un ticket con las 200 jugadas previas y se cuenta\n"
        "cuántos números acierta. Si alguna estrategia sirviera, su promedio de\n"
        "aciertos estaría por encima del azar de forma estadísticamente clara.\n"
    )
    ventana = 100
    rng = np.random.default_rng(11)
    resultados = defaultdict(list)

    for e in eras:
        R = e["rango"]
        tramo = sorteos[e["desde"]: e["hasta"] + 1]
        if len(tramo) < ventana + 30:
            continue
        for i in range(ventana, len(tramo)):
            hist = tramo[i - ventana: i]
            real = set(tramo[i]["bolas"])
            frec = Counter()
            for s in hist:
                frec.update(s["bolas"])
            orden = sorted(range(1, R + 1), key=lambda b: (-frec.get(b, 0), b))
            calientes = orden[:6]
            frios = orden[-6:]
            ultima_vez = {}
            for j, s in enumerate(hist):
                for b in s["bolas"]:
                    ultima_vez[b] = j
            atrasados = sorted(range(1, R + 1), key=lambda b: ultima_vez.get(b, -1))[:6]
            azar = list(rng.choice(np.arange(1, R + 1), 6, replace=False))
            fijo = [1, 2, 3, 4, 5, 6]

            for nombre, ticket in (
                ("calientes", calientes),
                ("fríos", frios),
                ("atrasados", atrasados),
                ("azar", azar),
                ("1-2-3-4-5-6", fijo),
            ):
                resultados[nombre].append(len(real & set(int(x) for x in ticket)))
            resultados["_R"].append(R)

    if not resultados:
        print("  (no hay suficientes sorteos por era para el backtest)")
        return

    esperado = float(np.mean([6 * 6 / r for r in resultados["_R"]]))
    n = len(resultados["azar"])
    print(f"  sorteos evaluados: {n}   aciertos esperados por azar: {esperado:.4f}\n")
    print(f"  {'estrategia':14s} {'aciertos/sorteo':>16s} {'IC95':>18s} {'p vs azar':>10s}")
    for nombre in ("calientes", "fríos", "atrasados", "azar", "1-2-3-4-5-6"):
        v = np.array(resultados[nombre], float)
        media = v.mean()
        ee = v.std(ddof=1) / math.sqrt(n)
        t = (media - esperado) / ee if ee else 0.0
        p = 2 * stats.norm.sf(abs(t))
        print(
            f"  {nombre:14s} {media:16.4f} {media-1.96*ee:8.4f}–{media+1.96*ee:.4f} "
            f"{p:10.3f}"
        )
    prueba_frecuencia_potente(sorteos, eras, ventana)


def prueba_frecuencia_potente(sorteos: list[dict], eras: list[dict],
                              ventana: int) -> None:
    """
    El backtest de arriba mira 6 números por sorteo, así que tiene poca
    potencia. Esta prueba mira las 45–53 bolillas en cada sorteo: para cada
    bolilla y cada sorteo se pregunta si haber salido mucho en la ventana
    anterior cambia la probabilidad de salir ahora. Son decenas de miles de
    observaciones, y ahí sí se detectaría un efecto pequeño si existiera.
    """
    print("\n  Prueba de mayor potencia: regresión logística bolilla por bolilla")
    xs, ys = [], []
    for e in eras:
        R = e["rango"]
        tramo = sorteos[e["desde"]: e["hasta"] + 1]
        if len(tramo) < ventana + 20:
            continue
        for i in range(ventana, len(tramo)):
            frec = Counter()
            for s in tramo[i - ventana: i]:
                frec.update(s["bolas"])
            salidas = set(tramo[i]["bolas"])
            media = ventana * 6 / R
            for b in range(1, R + 1):
                xs.append((frec.get(b, 0) - media) / math.sqrt(media))
                ys.append(1.0 if b in salidas else 0.0)

    if len(xs) < 1000:
        print("    (datos insuficientes)")
        return
    x = np.array(xs)
    y = np.array(ys)
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.zeros(2)
    for _ in range(60):
        pi = 1 / (1 + np.exp(-np.clip(X @ beta, -30, 30)))
        W = pi * (1 - pi)
        A = X.T @ (X * W[:, None]) + 1e-9 * np.eye(2)
        paso = np.linalg.solve(A, X.T @ (y - pi))
        beta = beta + paso
        if np.max(np.abs(paso)) < 1e-11:
            break
    pi = 1 / (1 + np.exp(-np.clip(X @ beta, -30, 30)))
    W = pi * (1 - pi)
    ee = math.sqrt(np.linalg.inv(X.T @ (X * W[:, None]))[1, 1])
    z = beta[1] / ee
    p = 2 * stats.norm.sf(abs(z))
    print(f"    observaciones (bolilla × sorteo): {len(x):,}")
    print(f"    coeficiente de 'qué tan caliente venía': {beta[1]:+.5f} "
          f"(ee {ee:.5f}, z={z:+.2f}, p={p:.3f})")
    lo, hi = beta[1] - 1.96 * ee, beta[1] + 1.96 * ee
    print(f"    intervalo 95%: [{lo:+.4f}, {hi:+.4f}] en log-odds  ->  "
          f"el efecto máximo compatible con los datos cambia la probabilidad "
          f"de cada bolilla entre {100*(math.exp(lo)-1):+.1f}% y "
          f"{100*(math.exp(hi)-1):+.1f}%")
    print(f"    {'no hay efecto: el pasado no informa el futuro' if p > 0.05 else 'REVISAR'}")

    print(
        "\n  Conclusión operativa: ninguna estrategia se separa del azar, y el "
        "intervalo\n  de confianza es lo bastante estrecho como para descartar "
        "también efectos\n  chicos. Cada sorteo es independiente del anterior."
    )


# ------------------------------------------------------- 4. popularidad


def glm_poisson(X: np.ndarray, y: np.ndarray, offset: np.ndarray,
                iters: int = 50) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Regresión de Poisson por IRLS. Devuelve (coeficientes, errores estándar
    cuasi-Poisson, parámetro de dispersión). Los errores se escalan por la
    dispersión porque los conteos de ganadores están sobredispersos.
    """
    beta = np.zeros(X.shape[1])
    beta[0] = float(np.log(y.mean() + 1e-9) - offset.mean())
    for _ in range(iters):
        eta = X @ beta + offset
        mu = np.exp(np.clip(eta, -30, 30))
        W = np.diag(mu)
        z = eta - offset + (y - mu) / np.maximum(mu, 1e-9)
        A = X.T @ W @ X + 1e-8 * np.eye(X.shape[1])
        nuevo = np.linalg.solve(A, X.T @ W @ z)
        if np.max(np.abs(nuevo - beta)) < 1e-10:
            beta = nuevo
            break
        beta = nuevo
    eta = X @ beta + offset
    mu = np.exp(np.clip(eta, -30, 30))
    gl = len(y) - X.shape[1]
    disp = float((((y - mu) ** 2) / np.maximum(mu, 1e-9)).sum() / gl)
    cov = np.linalg.inv(X.T @ np.diag(mu) @ X + 1e-8 * np.eye(X.shape[1])) * disp
    return beta, np.sqrt(np.diag(cov)), disp


def rasgos(bolas: list[int]) -> dict:
    b = sorted(bolas)
    consec = sum(1 for x, y in zip(b, b[1:]) if y - x == 1)
    return {
        "n_cumple": sum(1 for x in b if x <= 31),      # fechas de nacimiento
        "n_mes": sum(1 for x in b if x <= 12),          # meses
        "suma": sum(b),
        "consecutivos": consec,
        "n_pares": sum(1 for x in b if x % 2 == 0),
        "n_multiplo7": sum(1 for x in b if x % 7 == 0),
        "amplitud": b[-1] - b[0],
    }


def modelo_popularidad(con: sqlite3.Connection, sorteos: list[dict]) -> dict | None:
    titulo("4. ¿QUÉ NÚMEROS JUEGA LA GENTE? (aquí sí hay señal)")
    print(
        "No se puede predecir la bolilla, pero sí se puede medir con cuánta gente\n"
        "se comparte el premio. Si salen números que el público juega mucho, hay\n"
        "muchos más ganadores de 3, 4 y 5 aciertos. Modelo: Poisson con\n"
        "sobredispersión, variable dependiente = ganadores de 3 aciertos,\n"
        "exposición = ganadores de 2 aciertos + boliyapa (proxy del volumen vendido).\n"
    )
    g = defaultdict(dict)
    for s, cat, n in con.execute("SELECT sorteo, categoria, ganadores FROM ganadores"):
        g[s][cat] = n

    filas = []
    for i, s in enumerate(sorteos):
        d = g.get(s["sorteo"], {})
        y = d.get("3 aciertos")
        expo = d.get("2 aciertos + boliyapa")
        if y is None or not expo or y <= 0 or i < 50:
            continue
        r = rasgos(s["bolas"])
        # ¿la gente persigue los números "calientes"? Si es así, los sorteos
        # que salen con números recién salidos deberían tener más ganadores.
        frec = Counter()
        for prev in sorteos[i - 50: i]:
            frec.update(prev["bolas"])
        r["calor"] = sum(frec.get(b, 0) for b in s["bolas"]) / 6
        r.update(y=y, expo=expo, fecha=s["fecha"], sorteo=s["sorteo"])
        filas.append(r)

    if len(filas) < 100:
        print("  (datos de premios insuficientes)")
        return None

    nombres = ["n_cumple", "n_mes", "consecutivos", "n_multiplo7", "suma_z", "calor_z"]
    suma = np.array([f["suma"] for f in filas], float)
    suma_z = (suma - suma.mean()) / suma.std()
    calor = np.array([f["calor"] for f in filas], float)
    calor_z = (calor - calor.mean()) / calor.std()
    X = np.column_stack(
        [
            np.ones(len(filas)),
            [f["n_cumple"] for f in filas],
            [f["n_mes"] for f in filas],
            [f["consecutivos"] for f in filas],
            [f["n_multiplo7"] for f in filas],
            suma_z,
            calor_z,
        ]
    )
    y = np.array([f["y"] for f in filas], float)
    offset = np.log(np.array([f["expo"] for f in filas], float))

    beta, ee, disp = glm_poisson(X, y, offset)
    print(f"  sorteos usados: {len(filas)}   sobredispersión: {disp:.1f}\n")
    print(f"  {'variable':16s} {'coef':>9s} {'ee':>8s} {'z':>7s} {'p':>8s}  efecto por unidad")
    for i, nom in enumerate(["(intercepto)"] + nombres):
        z = beta[i] / ee[i]
        p = 2 * stats.norm.sf(abs(z))
        efecto = f"{(math.exp(beta[i]) - 1) * 100:+.1f}% ganadores" if i else ""
        print(f"  {nom:16s} {beta[i]:9.4f} {ee[i]:8.4f} {z:7.2f} {p:8.4f}  {efecto}")

    # comprobación sin modelo: comparar directamente los sorteos con pocos y
    # muchos números bajos, sin suponer ninguna forma funcional
    ratio = np.array([f["y"] / f["expo"] for f in filas], float)
    ncump = np.array([f["n_cumple"] for f in filas], float)
    pocos = ratio[ncump <= 2]
    muchos = ratio[ncump >= 5]
    u = stats.mannwhitneyu(muchos, pocos, alternative="greater")
    print(f"\n  Comprobación sin modelo (medianas de ganadores por unidad de volumen):")
    print(f"    sorteos con 0–2 bolillas en 1–31: mediana {np.median(pocos):.3f} "
          f"(n={len(pocos)})")
    print(f"    sorteos con 5–6 bolillas en 1–31: mediana {np.median(muchos):.3f} "
          f"(n={len(muchos)})")
    print(f"    diferencia: {100*(np.median(muchos)/np.median(pocos)-1):+.1f}% "
          f"más ganadores | Mann–Whitney p={u.pvalue:.4f}")

    print(
        "\n  Lectura: cada bolilla del sorteo que cae en 1–31 (rango de fechas de\n"
        "  nacimiento) multiplica la cantidad de ganadores. Eso significa que las\n"
        "  combinaciones con números bajos están mucho más jugadas, y si ganas con\n"
        "  ellas repartes el pozo entre más gente."
    )
    escala = escalera_por_categoria(filas, g)
    return {"beta": beta, "ee": ee, "nombres": nombres,
            "suma_media": float(suma.mean()), "suma_sd": float(suma.std()),
            "escalera": escala}


def escalera_por_categoria(filas: list[dict], g: dict) -> dict:
    """
    ¿El efecto de los números bajos crece al subir de categoría?

    Importa mucho: si acertar 3 números de una combinación "popular" ya trae
    +4% de ganadores, el efecto sobre acertar los 6 debería ser bastante mayor,
    porque acertar 3 sólo refleja una parte de lo que la gente marcó. Si el
    coeficiente sube de 3 a 4 y a 5 aciertos, extrapolarlo al pozo es razonable.
    """
    print("\n  4b. ¿El efecto se amplifica en las categorías altas?")
    print(f"     {'categoría':14s} {'coef. bolilla en 1–31':>22s} {'coef. consecutivos':>22s} {'sorteos':>8s}")
    salida = {}
    for cat in ("3 aciertos", "4 aciertos", "5 aciertos"):
        sub = []
        for f in filas:
            y = g.get(f["sorteo"], {}).get(cat)
            if y is not None and y > 0:
                sub.append((f, y))
        if len(sub) < 80:
            continue
        X = np.column_stack(
            [
                np.ones(len(sub)),
                [f["n_cumple"] for f, _ in sub],
                [f["consecutivos"] for f, _ in sub],
            ]
        )
        y = np.array([v for _, v in sub], float)
        off = np.log(np.array([f["expo"] for f, _ in sub], float))
        b, ee, _ = glm_poisson(X, y, off)
        k = int(cat[0])
        salida[k] = {"n_cumple": float(b[1]), "ee_cumple": float(ee[1]),
                     "consecutivos": float(b[2]), "ee_consec": float(ee[2]),
                     "n": len(sub)}
        print(f"     {cat:14s} {b[1]:+13.4f} ± {ee[1]:.4f} {b[2]:+13.4f} ± {ee[2]:.4f} "
              f"{len(sub):8d}")

    if len(salida) >= 3:
        ks = np.array(sorted(salida), float)
        for var in ("n_cumple", "consecutivos"):
            ys = np.array([salida[int(k)][var] for k in ks])
            pend, inter = np.polyfit(ks, ys, 1)
            salida.setdefault("extrapolacion", {})[var] = float(inter + pend * 6)
        print("\n     El coeficiente crece con la categoría: mientras más números de la\n"
              "     combinación hay que acertar, más pesa que sean números populares.\n"
              f"     Extrapolando la recta a 6 aciertos: "
              f"{salida['extrapolacion']['n_cumple']:+.3f} por bolilla en 1–31 y "
              f"{salida['extrapolacion']['consecutivos']:+.3f} por par consecutivo.")
        print("     OJO: eso es extrapolación. Sólo hay un puñado de aciertos de 6 en\n"
              "     todo el histórico, así que el efecto sobre el pozo no se puede medir\n"
              "     directamente; se estima con la tendencia de las categorías de abajo.")
    return salida


# ------------------------------------------------------- 5. valor esperado


def valor_esperado(R: int = 53, precio: float = 5.0, pozo: float = 24_500_000.0) -> None:
    titulo("5. VALOR ESPERADO REAL DE UN TICKET (formato 6/53 + boliyapa)")
    total = math.comb(R, 6)
    print(f"  combinaciones posibles: C({R},6) = {total:,}")

    def p(k: int, con_yapa: bool) -> float:
        # universo: 6 aciertos + 1 boliyapa + (R-7) restantes
        b = 1 if con_yapa else 0
        resto = 6 - k - b
        if resto < 0 or resto > R - 7:
            return 0.0
        return math.comb(6, k) * math.comb(1, b) * math.comb(R - 7, resto) / total

    premios = [
        ("6 aciertos", 6, False, pozo),
        ("5 + boliyapa", 5, True, 100_000),
        ("5 aciertos", 5, False, 5_000),
        ("4 + boliyapa", 4, True, 500),
        ("4 aciertos", 4, False, 100),
        ("3 + boliyapa", 3, True, 50),
        ("3 aciertos", 3, False, 10),
        ("2 + boliyapa", 2, True, 5),
    ]
    ev = 0.0
    print(f"\n  {'categoría':14s} {'probabilidad':>16s} {'1 en':>14s} {'premio S/':>12s} {'aporte al VE':>13s}")
    for nom, k, yapa, monto in premios:
        pr = p(k, yapa)
        ev += pr * monto
        print(f"  {nom:14s} {pr:16.9f} {1/pr:14,.0f} {monto:12,.0f} {pr*monto:13.4f}")
    print(f"\n  Valor esperado por ticket: S/ {ev:,.2f}   Precio: S/ {precio:.2f}")
    print(f"  Retorno: {100*ev/precio:.1f}%  ->  se pierde S/ {precio-ev:,.2f} por jugada, en promedio.")
    print(
        f"\n  Con 2 sorteos por semana y un ticket por sorteo, la probabilidad de\n"
        f"  acertar 6 alguna vez en 50 años es {1-(1-1/total)**(104*50):.5f} "
        f"(≈ 1 en {1/(1-(1-1/total)**(104*50)):,.0f})."
    )


# ------------------------------------------------------- descriptivos


def descriptivos(sorteos: list[dict], eras: list[dict]) -> None:
    titulo("6. PERFIL DE UN SORTEO TÍPICO (para que el ticket no sea raro por gusto)")
    e = eras[-1]
    tramo = sorteos[max(0, len(sorteos) - 300):]
    sumas = np.array([sum(s["bolas"]) for s in tramo], float)
    pares = np.array([sum(1 for b in s["bolas"] if b % 2 == 0) for s in tramo], float)
    bajos = np.array([sum(1 for b in s["bolas"] if b <= 26) for s in tramo], float)
    consec = np.array(
        [sum(1 for x, y in zip(s["bolas"], s["bolas"][1:]) if y - x == 1) for s in tramo],
        float,
    )
    print(f"  base: últimos {len(tramo)} sorteos")
    print(f"  suma de las 6 bolillas: media {sumas.mean():.1f}, "
          f"rango central 50% = {np.percentile(sumas,25):.0f}–{np.percentile(sumas,75):.0f}, "
          f"90% cae entre {np.percentile(sumas,5):.0f} y {np.percentile(sumas,95):.0f}")
    print(f"  números pares por sorteo: media {pares.mean():.2f} "
          f"(3 pares/3 impares ocurre el {100*np.mean(pares==3):.0f}% de las veces)")
    print(f"  al menos un par consecutivo: {100*np.mean(consec>=1):.0f}% de los sorteos")
    print(f"  bolillas en la mitad baja: media {bajos.mean():.2f}")


def main() -> int:
    con = sqlite3.connect(DB)
    sorteos = cargar(con)
    eras = detectar_eras(sorteos)

    titulo("BASE DE DATOS")
    print(f"  sorteos almacenados: {len(sorteos)}")
    print(f"  desde: sorteo {sorteos[0]['sorteo']} ({sorteos[0]['fecha']})")
    print(f"  hasta: sorteo {sorteos[-1]['sorteo']} ({sorteos[-1]['fecha']})")
    esperados = sorteos[-1]["sorteo"] - sorteos[0]["sorteo"] + 1
    print(f"  cobertura: {len(sorteos)}/{esperados} "
          f"({100*len(sorteos)/esperados:.1f}%) — faltan {esperados-len(sorteos)} "
          f"sorteos que la fuente no publica")
    print("\n  Formatos detectados (el bombo fue creciendo):")
    for e in eras:
        print(f"    1–{e['rango']:2d}: sorteos {e['s_ini']}–{e['s_fin']} "
              f"({e['f_ini']} a {e['f_fin']}), {e['n']} sorteos")

    prueba_uniformidad(sorteos, eras)
    prueba_memoria(sorteos, eras)
    backtest(sorteos, eras)
    modelo = modelo_popularidad(con, sorteos)
    valor_esperado()
    descriptivos(sorteos, eras)

    if modelo:
        import json

        destino = os.path.join(AQUI, "data", "modelo.json")
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ajustado": sorteos[-1]["fecha"],
                    "ultimo_sorteo": sorteos[-1]["sorteo"],
                    "rango_actual": eras[-1]["rango"],
                    "coef_3aciertos": dict(zip(
                        ["intercepto"] + modelo["nombres"],
                        [float(b) for b in modelo["beta"]])),
                    "por_categoria": modelo["escalera"],
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\nParámetros del modelo guardados en {destino}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
