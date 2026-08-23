"""
Extrae la tabla de ganadores por categoría de cada sorteo (usando el HTML ya
descargado en raw/) y la guarda en la tabla `ganadores`.

Estos conteos son la parte más valiosa de la base: no dicen nada sobre qué
bolillas van a salir, pero sí revelan cuánta gente jugó combinaciones
parecidas a la que salió. Con eso se puede estimar qué números elige el
público y, por lo tanto, con cuántas personas se compartiría un premio.
"""

from __future__ import annotations

import glob
import os
import re
import sqlite3

import scraper

AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(AQUI, "data", "tinka.sqlite")

CATEGORIAS = [
    "6 aciertos",
    "5 aciertos + boliyapa",
    "5 aciertos",
    "4 aciertos + boliyapa",
    "4 aciertos",
    "3 aciertos + boliyapa",
    "3 aciertos",
    "2 aciertos + boliyapa",
    "2 aciertos",
]

RE_SORTEO = re.compile(r"Resultados del Sorteo\s+(\d+)")


def parsear_ganadores(texto: str) -> dict[str, int]:
    """Devuelve {categoria: nº de ganadores} para el bloque de premios."""
    ini = texto.find("Gandores del Sorteo")
    fin = texto.find("Ganadores en el sorteo")
    if ini < 0:
        return {}
    bloque = texto[ini: fin if fin > ini else ini + 2000]

    salida: dict[str, int] = {}
    for cat in CATEGORIAS:
        # el número de ganadores es el primer entero que sigue al nombre de la
        # categoría; el "+ boliyapa" se busca antes que la versión corta para
        # que "5 aciertos" no se coma "5 aciertos + boliyapa".
        patron = re.escape(cat).replace(r"\ \+\ ", r"\s*\+\s*")
        m = re.search(patron + r"\s+([\d,]+)", bloque, re.I)
        if m:
            salida[cat] = int(m.group(1).replace(",", ""))
            bloque = bloque[: m.start()] + " " * (m.end() - m.start()) + bloque[m.end():]
    return salida


def main() -> int:
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS ganadores (
            sorteo    INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            ganadores INTEGER NOT NULL,
            PRIMARY KEY (sorteo, categoria)
        );
        """
    )

    filas = []
    for ruta in glob.glob(os.path.join(AQUI, "raw", "*.html")):
        doc = open(ruta, encoding="utf-8", errors="replace").read()
        texto = scraper.texto_plano(doc)
        m = RE_SORTEO.search(texto)
        if not m:
            continue
        sorteo = int(m.group(1))
        for cat, n in parsear_ganadores(texto).items():
            filas.append((sorteo, cat, n))

    con.executemany("INSERT OR REPLACE INTO ganadores VALUES (?,?,?)", filas)
    con.commit()

    n_sorteos = con.execute("SELECT COUNT(DISTINCT sorteo) FROM ganadores").fetchone()[0]
    print(f"Filas de premios guardadas: {len(filas)} en {n_sorteos} sorteos")
    for cat in CATEGORIAS:
        r = con.execute(
            "SELECT COUNT(*), AVG(ganadores) FROM ganadores WHERE categoria=?", (cat,)
        ).fetchone()
        print(f"  {cat:26s} sorteos={r[0]:4d}  promedio={r[1]:,.1f}" if r[1] else f"  {cat:26s} sorteos={r[0]:4d}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
