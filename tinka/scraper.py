"""
Descarga el histórico de sorteos de La Tinka y lo guarda en SQLite + CSV.

Fuente: tinkaresultados.com (sitio no oficial que publica una página por sorteo).
La fecha dentro de la URL es ignorada por el servidor: sólo cuenta el número de
sorteo, así que se puede recorrer el histórico por número.

Uso:
    python3 scraper.py --desde 1 --hasta 1400
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = "https://www.tinkaresultados.com/sorteos-historicos/jugada-{n}-del-1-1-2000"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

AQUI = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(AQUI, "raw")
DB = os.path.join(AQUI, "data", "tinka.sqlite")

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

RE_CABECERA = re.compile(
    r"Resultados del Sorteo\s+(\d+)\s+([a-záéíóú]+),\s*(\d{1,2})\s+de\s+([a-z]+)\s+(\d{4})"
)
RE_JUGADA = re.compile(r"Jugada Ganadora((?:\s+\d{1,2})+)")
RE_BOLIYAPA = re.compile(r"Boliyapa\s+(\d{1,2})")
RE_SIOSI = re.compile(r"S[íi] o s[íi]((?:\s+\d{1,2})+)")
RE_GANADORES_6 = re.compile(r"6 aciertos\s+([\d,]+)\s+s/\.\s*([\d'.,]+)", re.I)


def ruta_raw(n: int) -> str:
    return os.path.join(RAW, f"{n}.html")


def descargar(n: int, reintentos: int = 3, pausa: float = 0.6) -> str | None:
    """Devuelve el HTML del sorteo n, usando la caché en disco si ya existe."""
    destino = ruta_raw(n)
    if os.path.exists(destino) and os.path.getsize(destino) > 3000:
        with open(destino, encoding="utf-8", errors="replace") as f:
            return f.read()

    for intento in range(reintentos):
        try:
            req = urllib.request.Request(BASE.format(n=n), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo = r.read().decode("utf-8", errors="replace")
            with open(destino, "w", encoding="utf-8") as f:
                f.write(cuerpo)
            time.sleep(pausa)
            return cuerpo
        except urllib.error.HTTPError as e:
            if e.code in (404, 500):  # sorteo inexistente en la fuente
                return None
            time.sleep(2 ** intento)
        except Exception:
            time.sleep(2 ** intento)
    return None


def texto_plano(doc: str) -> str:
    doc = re.sub(r"(?is)<(script|style).*?</\1>", " ", doc)
    doc = re.sub(r"<[^>]*>", " ", doc)
    return re.sub(r"\s+", " ", html.unescape(doc))


def parsear(doc: str) -> dict | None:
    t = texto_plano(doc)
    cab = RE_CABECERA.search(t)
    if not cab:
        return None
    sorteo = int(cab.group(1))
    dia, mes_txt, anio = int(cab.group(3)), cab.group(4).lower(), int(cab.group(5))
    if mes_txt not in MESES:
        return None
    fecha = f"{anio:04d}-{MESES[mes_txt]:02d}-{dia:02d}"

    jug = RE_JUGADA.search(t)
    if not jug:
        return None
    bolas = [int(x) for x in jug.group(1).split()]
    if len(bolas) != 6 or len(set(bolas)) != 6:
        return None

    by = RE_BOLIYAPA.search(t)
    ss = RE_SIOSI.search(t)
    g6 = RE_GANADORES_6.search(t)

    return {
        "sorteo": sorteo,
        "fecha": fecha,
        "dia_semana": cab.group(2),
        "b1": bolas[0], "b2": bolas[1], "b3": bolas[2],
        "b4": bolas[3], "b5": bolas[4], "b6": bolas[5],
        "boliyapa": int(by.group(1)) if by else None,
        "si_o_si": " ".join(ss.group(1).split()) if ss else None,
        "ganadores_6": int(g6.group(1).replace(",", "")) if g6 else None,
        "pozo_6": g6.group(2) if g6 else None,
    }


def crear_esquema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS sorteos (
            sorteo      INTEGER PRIMARY KEY,
            fecha       TEXT NOT NULL,
            dia_semana  TEXT,
            b1 INTEGER, b2 INTEGER, b3 INTEGER,
            b4 INTEGER, b5 INTEGER, b6 INTEGER,
            boliyapa    INTEGER,
            si_o_si     TEXT,
            ganadores_6 INTEGER,
            pozo_6      TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_sorteos_fecha ON sorteos(fecha);
        """
    )
    con.commit()


def guardar(con: sqlite3.Connection, filas: list[dict]) -> None:
    con.executemany(
        """INSERT OR REPLACE INTO sorteos
           (sorteo, fecha, dia_semana, b1, b2, b3, b4, b5, b6,
            boliyapa, si_o_si, ganadores_6, pozo_6)
           VALUES (:sorteo, :fecha, :dia_semana, :b1, :b2, :b3, :b4, :b5, :b6,
                   :boliyapa, :si_o_si, :ganadores_6, :pozo_6)""",
        filas,
    )
    con.commit()


def exportar_csv(con: sqlite3.Connection, destino: str) -> int:
    import csv

    cur = con.execute("SELECT * FROM sorteos ORDER BY sorteo")
    cols = [d[0] for d in cur.description]
    filas = cur.fetchall()
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(filas)
    return len(filas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=1)
    ap.add_argument("--hasta", type=int, default=1400)
    ap.add_argument("--hilos", type=int, default=6)
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    os.makedirs(os.path.dirname(DB), exist_ok=True)

    numeros = list(range(args.desde, args.hasta + 1))
    ok, vacios = [], 0

    with cf.ThreadPoolExecutor(max_workers=args.hilos) as ex:
        for n, doc in zip(numeros, ex.map(descargar, numeros)):
            if not doc:
                vacios += 1
                continue
            fila = parsear(doc)
            if fila:
                ok.append(fila)
            else:
                vacios += 1
            if len(ok) % 100 == 0 and ok:
                print(f"  ... {len(ok)} sorteos leídos", file=sys.stderr)

    con = sqlite3.connect(DB)
    crear_esquema(con)
    guardar(con, ok)
    total = exportar_csv(con, os.path.join(AQUI, "data", "sorteos.csv"))

    print(f"Sorteos parseados en esta corrida: {len(ok)}  (sin datos: {vacios})")
    print(f"Total en la base: {total}")
    r = con.execute("SELECT MIN(fecha), MAX(fecha), MIN(sorteo), MAX(sorteo) FROM sorteos").fetchone()
    print(f"Rango: sorteo {r[2]}–{r[3]}, fechas {r[0]} a {r[1]}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
