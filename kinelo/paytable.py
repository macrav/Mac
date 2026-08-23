"""
Tabla de premios oficial de KINELO.

Fuente: Reglamento de la Lotería Electrónica KINELO, Artículo 26°.
https://www.latinka.com.pe/latinka/docs/reglamento/reglamento-kinelo.pdf

Mecánica (Artículos 1° inciso l, y 19°):
  - Un RNG certificado escoge, sin repetición, 20 números del 1 al 80.
  - El jugador elige entre 1 y 10 números ("tipo de apuesta").
  - Sorteos cada 5 minutos, de 06:00 a 02:00 del día siguiente.
  - Precio de la jugada simple: S/ 1.00.

PAYOUT[tipo][aciertos] = múltiplo de la apuesta que se paga.
Los aciertos que no aparecen en un tipo pagan 0.

Nota importante sobre los tipos 10, 9 y 8: pagan también por CERO aciertos
(2x, 1x y 1x respectivamente). Ese detalle cambia el retorno esperado y hay
que incluirlo en cualquier cálculo serio.
"""

# Parámetros del sorteo
POOL_SIZE = 80        # números del 1 al 80
DRAWN = 20            # el RNG saca 20
TICKET_PRICE = 1.00   # soles, jugada simple

# Multiplicadores disponibles en "MULTIPLICA TU PREMIO POR" (Artículo 6°)
MULTIPLIERS = (2, 3, 4, 5, 10, 20, 30, 40, 50)

PAYOUT = {
    10: {10: 100_000, 9: 10_000, 8: 500, 7: 50, 6: 20, 5: 2, 4: 1, 0: 2},
    9:  {9: 50_000, 8: 4_000, 7: 200, 6: 30, 5: 5, 4: 1, 0: 1},
    8:  {8: 20_000, 7: 1_000, 6: 50, 5: 10, 4: 2, 0: 1},
    7:  {7: 5_000, 6: 150, 5: 20, 4: 4, 3: 1},
    6:  {6: 2_000, 5: 55, 4: 8, 3: 1},
    5:  {5: 380, 4: 10, 3: 2, 2: 1},
    4:  {4: 120, 3: 5, 2: 1},
    3:  {3: 25, 2: 3},
    2:  {2: 6, 1: 1},
    1:  {1: 3},
}

# Artículo 27°: tope de S/ 1,000,000 por categoría y por sorteo para la
# primera categoría de los tipos 10, 9 y 8. Se reparte a prorrata entre los
# ganadores. Con apuesta de S/ 1 el premio nominal del tipo 10 es
# S/ 100,000, así que el tope solo muerde con multiplicadores altos o con
# varios ganadores simultáneos.
FIRST_CATEGORY_CAP = 1_000_000
CAPPED_TYPES = (10, 9, 8)


def payout_for(bet_type: int, hits: int) -> int:
    """Múltiplo pagado por `hits` aciertos en una jugada de `bet_type` números."""
    if bet_type not in PAYOUT:
        raise ValueError(f"tipo de apuesta inválido: {bet_type} (debe ser 1..10)")
    if not 0 <= hits <= bet_type:
        raise ValueError(f"aciertos fuera de rango: {hits} para tipo {bet_type}")
    return PAYOUT[bet_type].get(hits, 0)
