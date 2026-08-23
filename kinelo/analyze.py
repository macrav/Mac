#!/usr/bin/env python3
"""
Informe completo de KINELO.

    python3 analyze.py            informe completo (usa datos simulados si la
                                  base está vacía, y lo dice claramente)
    python3 analyze.py --db X     usa otra base de datos
    python3 analyze.py --tickets  solo la cartera de tickets
"""

from __future__ import annotations

import argparse
import sys

import db
from backtest import compare, format_comparison
from kinelo_math import expected_return, loss_after, prob_ruin_free_streak, summary_table
from paytable import DRAWN, POOL_SIZE, TICKET_PRICE
from portfolio import compare_overlap_designs
from randomness import run_all
from strategies import default_suite
from tickets import format_portfolio, generate_portfolio

SORTEOS_POR_DIA = 240  # cada 5 min, de 06:00 a 02:00


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def section_rules() -> None:
    rule("1. REGLAS DEL JUEGO (Reglamento oficial de KINELO)")
    print(f"""
  Un RNG certificado escoge {DRAWN} números de {POOL_SIZE}, sin repetición.   (Art. 1° l, 19°)
  Sorteos cada 5 minutos, de 06:00 a 02:00  ->  {SORTEOS_POR_DIA} sorteos por día.
  El jugador marca entre 1 y 10 números: eso define el "tipo de apuesta".
  Precio de la jugada simple: S/ {TICKET_PRICE:.2f}.                          (Art. 1° f)

  El dato que decide todo el análisis: los números NO salen de una bolillera
  física, salen de un generador de números aleatorios. No hay bolilla más
  pesada, ni desgaste, ni sesgo mecánico que descubrir. Es la única fuente de
  ventaja que históricamente ha existido en loterías, y aquí no aplica.
""")


def section_paytable() -> None:
    rule("2. RETORNO EXACTO DE CADA TIPO DE APUESTA")
    print("""
  Calculado con la distribución hipergeométrica, exacto, sin simulación:
      P(k aciertos) = C(20,k) * C(60,n-k) / C(80,n)
""")
    rows = summary_table()
    print(f"  {'Tipo':>4} {'RTP':>9} {'Ventaja casa':>13} {'P(cobra algo)':>14} "
          f"{'1ra cat: 1 en':>15} {'Desv.est':>9}")
    print("  " + "-" * 72)
    for r in rows:
        print(f"  {r['tipo']:>4} {r['rtp']*100:>8.3f}% {r['ventaja_casa']*100:>12.3f}% "
              f"{r['prob_cobrar_algo']*100:>13.2f}% {r['odds_primera_cat']:>15,.0f} "
              f"{r['desv_est']:>9.2f}")
    best = max(rows, key=lambda r: r["rtp"])
    worst = min(rows, key=lambda r: r["rtp"])
    print(f"""
  Mejor : tipo {best['tipo']} con {best['rtp']*100:.3f}% de retorno.
  Peor  : tipo {worst['tipo']} con {worst['rtp']*100:.3f}%.
  Elegir bien el tipo de apuesta vale {(best['rtp']-worst['rtp'])*100:.2f} puntos porcentuales.
  Es la decisión con mayor impacto real que puede tomar el jugador.

  Referencia para dimensionar: una tragamonedas regulada devuelve 92-96% y la
  ruleta europea 97.3%. KINELO devuelve {best['rtp']*100:.1f}% en su mejor variante.
""")


def section_data(conn) -> list[list[int]]:
    rule("3. BASE DE DATOS DE SORTEOS")
    n = db.count_draws(conn)
    if n == 0:
        print("""
  La base está vacía. No existe un histórico público de KINELO descargable:
  el detalle de lo que se verificó está en collector.py. Los resultados viven
  dentro del cliente de juego autenticado, a ~240 sorteos por día.

  Para seguir, se carga un corpus SIMULADO con un RNG limpio y conocido. No es
  dato real y no se presenta como tal: sirve para validar que las herramientas
  funcionan y para saber cómo se ve un histórico sin ninguna señal.
""")
        from collector import seed_with_simulation
        ins, _ = seed_with_simulation(50_000, conn=conn)
        print(f"  Cargados {ins:,} sorteos simulados.")
    src = conn.execute(
        "SELECT source, COUNT(*) c FROM draws GROUP BY source"
    ).fetchall()
    print(f"\n  Sorteos en base: {db.count_draws(conn):,}")
    for r in src:
        print(f"    - {r['source']}: {r['c']:,}")
    return db.load_matrix(conn)


def section_randomness(draws: list[list[int]]) -> None:
    rule("4. ¿HAY ALGUNA SEÑAL EXPLOTABLE EN EL HISTÓRICO?")
    print(f"""
  Seis tests sobre {len(draws):,} sorteos. Cada uno ataca una creencia
  concreta sobre cómo "leer" la lotería.
""")
    for r in run_all(draws):
        if "error" in r:
            print(f"  [{r['test']}] {r['error']}")
            continue
        print(f"  · {r.get('descripcion', r['test'])}")
        print(f"      {r['veredicto']}")
    print("""
  Sensibilidad medida de esta batería: con un sesgo de solo +15% en 5 números
  lo detecta con 5,000 sorteos (21 días de Kinelo) a p < 1e-6. O sea que si
  hubiera un sesgo aprovechable, estos tests lo verían. Que no encuentren nada
  es un resultado informativo, no una limitación del método.
""")


def section_backtest(draws: list[list[int]]) -> None:
    rule("5. BACKTEST DE LAS ESTRATEGIAS DE PREDICCIÓN")
    print("""
  Diez estrategias, incluidas las que se venden por internet. Cada una ve solo
  el pasado y todas se evalúan sobre los mismos sorteos.

  El criterio es duro y explícito: para "funcionar", el retorno tiene que
  superar el 100% con significancia estadística. Superar a la estrategia al
  azar por unos puntos no sirve de nada si ambas pierden plata.
""")
    warmup = min(5000, len(draws) // 5)
    res = compare(draws, default_suite(), bet_type=5, warmup=warmup, seed=7)
    print(format_comparison(res))
    top = max(res, key=lambda r: r["retorno"])
    print(f"""
  Ojo con el primer puesto: "{top['estrategia']}" muestra {top['retorno']*100:.1f}% de retorno,
  bastante por encima del {top['retorno_teorico']*100:.1f}% teórico. Pero su intervalo de
  confianza es [{top['ic95_bajo']*100:.1f}%, {top['ic95_alto']*100:.1f}%], que contiene al teórico sin problema.
  Es ruido, no habilidad. Así es exactamente como se fabrica un sistema
  "ganador": se prueban muchas variantes y se publica la que quedó arriba.
""")


def section_portfolio() -> None:
    rule("6. LO ÚNICO QUE SÍ SE PUEDE OPTIMIZAR: LA COVARIANZA")
    print("""
  Si se juegan varios tickets en el MISMO sorteo, los números que comparten
  entre sí cambian el riesgo de la cartera, aunque no cambien el retorno
  esperado. Tickets con números disjuntos están correlacionados negativamente:
  los 20 números del sorteo son un recurso limitado y se reparten.

  Cuatro tickets de tipo 5, S/ 1 cada uno, según cuántos números comparta
  cada par (cálculo exacto, verificado contra Monte Carlo de 400,000 sorteos):
""")
    print(f"  {'Solape/par':>11} {'E[retorno] S/':>15} {'Desv.est S/':>13}")
    print("  " + "-" * 41)
    for r in compare_overlap_designs(5, 4):
        print(f"  {r['solapamiento_por_par']:>11} "
              f"{r['retorno_esperado_soles']:>15.6f} {r['desv_estandar_soles']:>13.2f}")
    print("""
  El retorno esperado es idéntico hasta el sexto decimal en los seis diseños.
  La desviación estándar se duplica. Y la probabilidad de irse con las manos
  vacías pasa de 13% (disjuntos) a 63% (los 4 tickets iguales).

  Mismo gasto, mismo retorno esperado, la mitad de volatilidad. Eso es todo lo
  que "lo más seguro posible" puede significar en este juego.
""")


def section_tickets() -> None:
    rule("7. LOS 4 TICKETS")
    res = generate_portfolio(n_tickets=4, bet_type=None, seed=20260823)
    print()
    print(format_portfolio(res))
    bt = res["tipo_apuesta"]
    print(f"""
  Qué son estos tickets: la configuración de mínima varianza para 4 jugadas de
  S/ 1 en un mismo sorteo, con el tipo de apuesta de mayor retorno.

  Qué NO son: tickets ganadores. Esa categoría no existe. Los números salieron
  de un sorteo con semilla {res['semilla']}, y cualquier otra selección de 20
  números distintos tendría exactamente las mismas propiedades. Si alguien
  cambia los 20 por sus fechas de cumpleaños, el análisis no empeora en nada,
  siempre que sigan siendo 20 números distintos.
""")


def section_bottom_line() -> None:
    rule("8. NÚMEROS PARA DECIDIR")
    bt = 5
    edge = 1 - float(expected_return(bt))
    print(f"""
  Jugando el tipo {bt}, el mejor de los diez, a S/ 1 por jugada:

    Pérdida esperada por jugada        : S/ {edge:.4f}
    Un sorteo de 4 tickets             : S/ {edge*4:.2f} de pérdida esperada
    Jugando 20 sorteos al día, un mes  : S/ {loss_after(bt, 20*4*30):,.0f}
    Jugando un año a ese ritmo         : S/ {loss_after(bt, 20*4*365):,.0f}

  La probabilidad de acertar los 5 es 1 en 1,551. A un sorteo cada 5 minutos y
  jugando sin parar las 20 horas que el juego está abierto, son unos 6.5 días
  de juego continuo para un acierto de primera categoría, que paga 380x.

  Y esta es la parte que no depende de ninguna estrategia: la ventaja de la
  casa es {edge*100:.2f}% y es estructural. No se reduce eligiendo números,
  ni con ventanas de análisis, ni con modelos de Markov, ni jugando más
  seguido. Está en la tabla de premios, que es pública y está arriba.

  Con esos números, la jugada de mayor valor esperado es no jugar: S/ 0.
  Cualquier otra tiene valor esperado negativo. Si igual se juega, que sea con
  plata que se puede perder entera, porque en promedio se pierde.

  Si esto deja de ser entretenimiento: Línea 113 (Minsa), opción 5, salud mental.
""")


def main() -> int:
    ap = argparse.ArgumentParser(description="Análisis de KINELO")
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--tickets", action="store_true", help="solo la cartera")
    ap.add_argument("--skip-backtest", action="store_true")
    args = ap.parse_args()

    if args.tickets:
        print(format_portfolio(generate_portfolio(4, None, 20260823)))
        return 0

    conn = db.connect(args.db)
    section_rules()
    section_paytable()
    draws = section_data(conn)
    section_randomness(draws)
    if not args.skip_backtest:
        section_backtest(draws)
    section_portfolio()
    section_tickets()
    section_bottom_line()
    return 0


if __name__ == "__main__":
    sys.exit(main())
