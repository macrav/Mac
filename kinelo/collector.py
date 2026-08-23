"""
Colector de resultados de KINELO.

ESTADO DEL ACCESO A DATOS (verificado el 2026-08-23)
----------------------------------------------------
No existe hoy un histórico público de sorteos de KINELO que se pueda
descargar. Esto es lo que se comprobó, una por una:

  * https://m.latinka.com.pe/game_kinelo_show_home.html devuelve exactamente
    el mismo HTML (105,629 bytes, md5 4059153eea…) para CUALQUIER ruta,
    incluidas rutas inventadas. Es una shell que se arma en el cliente; no
    hay resultados de Kinelo en el HTML servido.

  * El backend de resultados de La Tinka es `i.do?m=resultados&t=1&s=<id>`,
    con s=1121 para Kinelo (sacado de layer-view-script/common/utils.js).
    Ese endpoint responde 404 en www.latinka.com.pe y cae en la shell en
    m.latinka.com.pe: no es alcanzable sin sesión iniciada.

  * https://www.latinka.com.pe/intralot/swf/intralot/games.xml sí publica
    resultados, pero solo de Tinka, Kábala, Ganagol y Gana Diario. Kinelo no
    está: al ser un juego de 5 minutos son ~240 sorteos por día y no se
    publica en ese feed.

  * www.kinelo.com.pe (el sitio que el Reglamento, Art. 21°, señala como
    lugar de publicación de resultados) no resuelve desde fuera del Perú.

Conclusión práctica: los resultados están dentro del cliente de juego
autenticado. Para armar el histórico hay que capturarlos en vivo desde una
sesión propia, a razón de ~240 sorteos por día.

Las dos vías que sí funcionan están abajo. `ingest_manual` es la que se puede
usar hoy mismo; `ingest_from_api` queda lista para el día que se identifique
el endpoint autenticado.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import db
from paytable import DRAWN

# Endpoint de resultados de La Tinka. Kinelo es el juego 1121.
# Requiere sesión autenticada; se deja documentado, no cableado.
RESULTS_ENDPOINT_TEMPLATE = "i.do?m=resultados&t=1&s={game_id}"
KINELO_GAME_ID = 1121


def parse_draw_line(line: str) -> tuple[int, str, list[int]] | None:
    """
    Parsea una línea de texto con un sorteo.

    Formatos aceptados (uno por línea):
        12345 | 2026-08-23T14:35:00 | 3,7,11,...
        12345,2026-08-23T14:35:00,3 7 11 ...
        2026-08-23 14:35 3 7 11 ...        (sin id: se numera solo)

    Ignora líneas en blanco y las que empiezan con #.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    parts = [p.strip() for p in re.split(r"[|;]", line)] if ("|" in line or ";" in line) else None
    if parts and len(parts) >= 3:
        draw_id = int(re.sub(r"\D", "", parts[0]))
        when = parts[1]
        nums = [int(x) for x in re.findall(r"\d+", parts[2])]
        return draw_id, when, nums

    tokens = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?|\d+", line)
    when = next((t for t in tokens if "-" in t), None)
    nums = [int(t) for t in tokens if "-" not in t]
    if when is None or len(nums) < DRAWN:
        return None
    # Si sobra un número al inicio, es el id del sorteo.
    draw_id = nums[0] if len(nums) == DRAWN + 1 else 0
    numbers = nums[-DRAWN:]
    return draw_id, when.replace(" ", "T"), numbers


def ingest_manual(path: str | Path, conn=None, source: str = "manual") -> tuple[int, int]:
    """
    Carga sorteos desde un archivo de texto.

    Es la vía que funciona hoy: se copian los resultados desde el cliente de
    juego y se pegan en un .txt. Ver data/ejemplo_sorteos.txt.
    """
    conn = conn or db.connect()
    rows, auto_id = [], 1
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        parsed = parse_draw_line(raw)
        if parsed is None:
            continue
        draw_id, when, nums = parsed
        if draw_id == 0:
            draw_id = auto_id
            auto_id += 1
        rows.append((draw_id, when, nums))
    ins, skip = db.insert_draws(conn, rows, source)
    db.rebuild_frequencies(conn)
    return ins, skip


def ingest_from_json(path: str | Path, conn=None, source: str = "json") -> tuple[int, int]:
    """
    Carga desde un JSON: [{"draw_id":…, "drawn_at":…, "numbers":[…]}, …]

    Es el formato que conviene si se captura la respuesta del cliente de juego
    desde las herramientas de desarrollador del navegador.
    """
    conn = conn or db.connect()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = [
        (int(d["draw_id"]), str(d["drawn_at"]), [int(n) for n in d["numbers"]])
        for d in data
    ]
    ins, skip = db.insert_draws(conn, rows, source)
    db.rebuild_frequencies(conn)
    return ins, skip


def ingest_from_api(fetch_fn, conn=None, source: str = "api") -> tuple[int, int]:
    """
    Punto de enganche para cuando se disponga del endpoint autenticado.

    `fetch_fn` debe devolver un iterable de (draw_id, drawn_at_iso, numeros).
    Se aísla así para que el resto del sistema no dependa de cómo se obtengan
    los datos.
    """
    conn = conn or db.connect()
    rows: Iterable = fetch_fn()
    ins, skip = db.insert_draws(conn, rows, source)
    db.rebuild_frequencies(conn)
    return ins, skip


def seed_with_simulation(n: int = 50_000, seed: int = 2026, conn=None) -> tuple[int, int]:
    """
    Llena la base con sorteos SIMULADOS de un RNG limpio.

    Sirve para validar el pipeline y para tener la referencia de "así se ve un
    histórico sin ninguna señal". Se marca como 'simulado' en la columna
    `source` para que no haya forma de confundirlo con datos reales.
    """
    from simulate import fair_draws, with_timestamps

    conn = conn or db.connect()
    rows = with_timestamps(fair_draws(n, seed=seed),
                           start=datetime(2026, 1, 1, 6, 0, 0))
    ins, skip = db.insert_draws(conn, rows, f"simulado(seed={seed})")
    db.rebuild_frequencies(conn)
    return ins, skip
