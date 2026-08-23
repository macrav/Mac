"""
Generador de tickets para La Tinka.

Qué hace y qué NO hace, para que no haya malentendidos:

  NO predice qué bolillas van a salir. El análisis (ver analisis.py) muestra
  que el sorteo es uniforme y sin memoria: todas las combinaciones tienen
  exactamente la misma probabilidad, 1 en 22,957,480. Ningún ticket puede
  mejorar eso.

  SÍ optimiza lo único que se puede optimizar: con cuánta gente se comparte
  el premio si toca. Los datos de ganadores por sorteo muestran que las
  combinaciones con números del 1 al 31 (fechas de nacimiento) están mucho
  más jugadas, y que la gente evita los números consecutivos. Elegir contra
  esa preferencia no cambia la probabilidad de ganar, pero aumenta lo que
  se cobra en caso de ganar.

Uso:
    python3 generador.py --tickets 4
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3

AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(AQUI, "data", "tinka.sqlite")
MODELO = os.path.join(AQUI, "data", "modelo.json")

# Cuántos números del ticket pueden caer en 1–31 (el rango de fechas de
# nacimiento, que es el que la gente sobrejuega). Cero es lo óptimo. La
# magnitud exacta del beneficio en cero es extrapolada —sólo hay 1 sorteo
# histórico sin ningún número en 1–31— pero la dirección no admite duda:
# menos números populares nunca puede significar más gente con quien repartir.
MIN_CUMPLE, MAX_CUMPLE = 0, 1

# Pares de números seguidos (32-33 cuenta como uno). La gente los evita, así
# que incluirlos reduce el reparto. Se limita a 2 porque más que eso no tiene
# respaldo en los datos: sólo 11 sorteos de 837 tuvieron 3 o más.
MIN_CONSEC, MAX_CONSEC = 1, 2

# Máximo de números compartidos entre dos tickets. Con sólo 22 números por
# encima del 31, cuatro tickets no pueden ser disjuntos sin meter números
# populares; se admite algo de solapamiento antes que empeorar el reparto.
MAX_SOLAPE = 2


def rasgos(b: tuple[int, ...]) -> dict:
    b = tuple(sorted(b))
    return {
        "n_cumple": sum(1 for x in b if x <= 31),
        "consecutivos": sum(1 for x, y in zip(b, b[1:]) if y - x == 1),
        "suma": sum(b),
        "n_pares": sum(1 for x in b if x % 2 == 0),
        "amplitud": b[-1] - b[0],
    }


def promedio_azar(R: int) -> dict:
    """Valores esperados de una combinación tomada completamente al azar."""
    e_cumple = 6 * min(31, R) / R
    # nº esperado de pares seguidos: hay R-1 pares posibles (v, v+1) y cada uno
    # está completo si los otros 4 números salen del resto
    e_consec = (R - 1) * math.comb(R - 2, 4) / math.comb(R, 6)
    return {"n_cumple": e_cumple, "consecutivos": e_consec}


def es_patron_evidente(b: tuple[int, ...]) -> str | None:
    """
    Filtros de patrones que mucha gente marca y que el modelo no captura.
    No cambian la probabilidad (todas las combinaciones son equiprobables),
    pero evitarlos es gratis y reduce el riesgo de compartir el premio.
    """
    b = tuple(sorted(b))
    difs = [y - x for x, y in zip(b, b[1:])]
    if len(set(difs)) == 1:
        return "progresión aritmética (5-10-15-20-25-30 y similares)"
    if max(difs) == 1:
        return "seis números seguidos"
    from collections import Counter

    finales = Counter(x % 10 for x in b)
    if max(finales.values()) >= 3:
        return "tres o más números terminados en la misma cifra"
    decenas = Counter(x // 10 for x in b)
    if max(decenas.values()) >= 4:
        return "cuatro o más números de la misma decena"
    if all(x % 2 == 0 for x in b) or all(x % 2 == 1 for x in b):
        return "todos pares o todos impares"
    return None


def cargar_historicos(con: sqlite3.Connection) -> set[tuple[int, ...]]:
    return {
        tuple(sorted(r))
        for r in con.execute("SELECT b1,b2,b3,b4,b5,b6 FROM sorteos")
    }


def puntaje(b: tuple[int, ...], coef: dict, base: dict,
            pop: dict | None = None, escala: float = 1.0) -> float:
    """
    Índice de cuánta gente comparte el premio, relativo a una combinación
    tomada al azar (1.00 = lo normal; 0.70 = se reparte con 30% menos gente).

    Dos términos:
      - la banda a la que pertenece cada número (1–31 muy jugado): efecto
        grande y bien medido
      - el desvío propio de cada número dentro de su banda: evidencia débil,
        así que entra encogido (ver popularidad.py)
    """
    r = rasgos(b)
    log = coef["consecutivos"] * (r["consecutivos"] - base["consecutivos"])
    if pop:
        # el índice por número ya incluye la diferencia bajos/altos
        log += escala * sum(math.log(pop[str(x)]) for x in b)
        log -= escala * 6 * base["log_pop_medio"]
    else:
        log += coef["n_cumple"] * (r["n_cumple"] - base["n_cumple"])
    return math.exp(log)


def probabilidades(R: int) -> list[tuple[str, float, float]]:
    total = math.comb(R, 6)

    def p(k: int, yapa: bool) -> float:
        b = 1 if yapa else 0
        resto = 6 - k - b
        if resto < 0 or resto > R - 7:
            return 0.0
        return math.comb(6, k) * math.comb(1, b) * math.comb(R - 7, resto) / total

    return [
        ("6 aciertos (pozo)", p(6, False), 0),
        ("5 + boliyapa", p(5, True), 100_000),
        ("5 aciertos", p(5, False), 5_000),
        ("4 + boliyapa", p(4, True), 500),
        ("4 aciertos", p(4, False), 100),
        ("3 + boliyapa", p(3, True), 50),
        ("3 aciertos", p(3, False), 10),
        ("2 + boliyapa", p(2, True), 5),
    ]


def generar(n_tickets: int, R: int, coef: dict, historicos: set, semilla: int,
            pop: dict | None, escala: float,
            candidatos: int = 600_000) -> list[tuple]:
    rng = random.Random(semilla)
    base = promedio_azar(R)
    if pop:
        base["log_pop_medio"] = sum(
            math.log(pop[str(x)]) for x in range(1, R + 1)
        ) / R
    numeros = list(range(1, R + 1))

    evaluados = []
    vistos = set()
    for _ in range(candidatos):
        b = tuple(sorted(rng.sample(numeros, 6)))
        if b in vistos:
            continue
        vistos.add(b)
        r = rasgos(b)
        if not (MIN_CUMPLE <= r["n_cumple"] <= MAX_CUMPLE):
            continue
        if not (MIN_CONSEC <= r["consecutivos"] <= MAX_CONSEC):
            continue
        if b in historicos:          # la gente juega combinaciones que ya salieron
            continue
        if es_patron_evidente(b):
            continue
        # Desempate: dentro del 1–31 el modelo no distingue un número de otro
        # (esa diferencia resultó ser ruido), pero el 1–12 sirve además como
        # mes y el punto estimado lo daba algo más jugado. Cuando hay que
        # meter un número bajo, se prefiere del 13 al 31. No cuesta nada.
        castigo = 0.001 * sum(1 for x in b if x <= 12)
        evaluados.append((puntaje(b, coef, base, pop, escala) + castigo, b))

    evaluados.sort()
    if not evaluados:
        return []

    # Miles de combinaciones empatan en el óptimo: para el modelo son
    # indistinguibles. Entre las empatadas se eligen las que menos se pisan
    # entre sí. No aumenta la probabilidad de ganar el pozo (nada la aumenta),
    # pero descorrelaciona los premios chicos y sube la probabilidad de cobrar
    # algo en el sorteo.
    mejor = evaluados[0][0]
    empatadas = [(s, b) for s, b in evaluados if s <= mejor * 1.02]
    rng.shuffle(empatadas)

    elegidos: list[tuple] = [empatadas[0]]
    while len(elegidos) < n_tickets:
        candidata = min(
            empatadas,
            key=lambda sb: (
                max(len(set(sb[1]) & set(o)) for _, o in elegidos),
                sum(len(set(sb[1]) & set(o)) for _, o in elegidos),
                sb[0],
            ),
        )
        if any(candidata[1] == b for _, b in elegidos):
            break
        elegidos.append(candidata)
    return [(s, b) for s, b in elegidos]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickets", type=int, default=4)
    ap.add_argument("--semilla", type=int, default=20260823)
    args = ap.parse_args()

    with open(MODELO, encoding="utf-8") as f:
        modelo = json.load(f)
    R = modelo["rango_actual"]
    coef = modelo["por_categoria"]["extrapolacion"]

    # el índice por número se estimó sobre "4 aciertos"; el efecto crece con la
    # categoría, así que se reescala a la altura del pozo (6 aciertos)
    pop, escala = None, 1.0
    ruta_pop = os.path.join(AQUI, "data", "popularidad.json")
    if os.path.exists(ruta_pop):
        with open(ruta_pop, encoding="utf-8") as f:
            pop = json.load(f)["indice"]
        escala = (modelo["por_categoria"]["extrapolacion"]["n_cumple"]
                  / modelo["por_categoria"]["4"]["n_cumple"])

    con = sqlite3.connect(DB)
    historicos = cargar_historicos(con)
    con.close()

    total = math.comb(R, 6)
    print("=" * 78)
    print(f"TICKETS PARA LA TINKA — formato 6/{R} + boliyapa")
    print(f"modelo ajustado hasta el sorteo {modelo['ultimo_sorteo']} "
          f"({modelo['ajustado']})")
    print("=" * 78)
    print(f"\nProbabilidad de acertar los 6: 1 en {total:,}. Es idéntica para")
    print("estos tickets, para el 1-2-3-4-5-6 y para cualquier otra combinación.")
    print("Lo único que cambia entre tickets es con cuánta gente se comparte.\n")

    elegidos = generar(args.tickets, R, coef, historicos, args.semilla,
                       pop, escala)

    print(f"{'#':>2}  {'números':28s} {'suma':>5s} {'en 1–31':>8s} {'seguidos':>9s} "
          f"{'a repartir':>11s}")
    for i, (s, b) in enumerate(elegidos, 1):
        r = rasgos(b)
        nums = " - ".join(f"{x:02d}" for x in b)
        print(f"{i:2d}  {nums:28s} {r['suma']:5d} {r['n_cumple']:8d} "
              f"{r['consecutivos']:9d} {s:10.2f}x")

    medio = sum(s for s, _ in elegidos) / len(elegidos)
    print(f"\nÍndice de reparto promedio: {medio:.2f}x contra 1.00x de una jugada")
    print(f"al azar. Traducido: si el pozo cae en uno de estos tickets, se espera")
    print(f"repartirlo con {100*(1-medio):.0f}% menos gente que con una jugada")
    print("típica. No es que gane más veces: es que cobra más cuando gane.")

    # ¿cuánto de ese número depende de extrapolar? Se recalcula usando sólo
    # coeficientes medidos directamente (los de la categoría de 5 aciertos).
    coef5 = {"consecutivos": modelo["por_categoria"]["5"]["consecutivos"]}
    escala5 = (modelo["por_categoria"]["5"]["n_cumple"]
               / modelo["por_categoria"]["4"]["n_cumple"])
    base = promedio_azar(R)
    if pop:
        base["log_pop_medio"] = sum(math.log(pop[str(x)])
                                    for x in range(1, R + 1)) / R
    medio5 = sum(puntaje(b, coef5, base, pop, escala5)
                 for _, b in elegidos) / len(elegidos)
    print(f"\nSensibilidad: ese {medio:.2f}x sale de extrapolar el efecto hasta la")
    print(f"categoría del pozo. Usando sólo lo medido directamente (5 aciertos,")
    print(f"sin extrapolar) el índice sería {medio5:.2f}x. La conclusión aguanta")
    print("en todo ese rango, pero la cifra exacta no hay que tomársela al pie")
    print("de la letra.")

    print("\nProbabilidades por categoría (iguales para cualquier ticket):")
    for nom, p, premio in probabilidades(R):
        etiqueta = f"S/ {premio:,}" if premio else "el pozo"
        print(f"  {nom:20s} 1 en {1/p:12,.0f}   {etiqueta}")

    ev = sum(p * premio for _, p, premio in probabilidades(R))
    ev += probabilidades(R)[0][1] * 24_500_000
    print(f"\nValor esperado de cada ticket: S/ {ev:.2f} (con el pozo en S/ 24.5 M)")
    print(f"Precio: S/ 5.00. Se pierde S/ {5-ev:.2f} por jugada, en promedio, y")
    print("esto no lo arregla ningún modelo: la casa se queda con la diferencia.")
    print(f"\nSemilla usada: {args.semilla} (reproducible con --semilla)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
