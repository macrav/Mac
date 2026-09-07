"""Matematica del credito hipotecario en soles.

Modelo: cuota francesa (cuota constante) sobre el prestamo, mas dos seguros
mensuales tipicos de la banca peruana:

  cuota_total(mes) = amortizacion + desgravamen * saldo(mes) + seguro_inmueble * valor

El desgravamen baja mes a mes porque el saldo baja. La cuota mas alta es la del
primer mes, asi que todos los calculos de "cuanto me alcanza" usan ese mes: si
la primera cuota entra en el presupuesto, todas las demas tambien.
"""

from dataclasses import dataclass

from .config import SupuestosCredito


def tem_desde_tea(tea: float) -> float:
    """Tasa efectiva mensual a partir de la tasa efectiva anual."""
    return (1.0 + tea) ** (1.0 / 12.0) - 1.0


def factor_cuota(tem: float, meses: int) -> float:
    """Factor de anualidad: cuota = prestamo * factor."""
    if meses <= 0:
        raise ValueError("el plazo debe ser mayor a cero")
    if tem == 0:
        return 1.0 / meses
    return tem / (1.0 - (1.0 + tem) ** (-meses))


def cuota_amortizacion(prestamo: float, tea: float, meses: int) -> float:
    return prestamo * factor_cuota(tem_desde_tea(tea), meses)


@dataclass
class Cuota:
    precio: float          # valor del inmueble en soles
    inicial: float         # cuota inicial en soles
    prestamo: float
    amortizacion: float    # parte fija de la cuota
    desgravamen: float     # primer mes (el mas caro)
    seguro_inmueble: float
    portes: float
    total: float           # cuota total del primer mes
    tea: float
    meses: int

    @property
    def inicial_pct(self) -> float:
        return self.inicial / self.precio if self.precio else 0.0


def cuota_mensual(precio: float, inicial: float, c: SupuestosCredito) -> Cuota:
    """Cuota total del primer mes para un precio y una inicial dados."""
    prestamo = max(precio - inicial - c.bono_buen_pagador, 0.0)
    amort = cuota_amortizacion(prestamo, c.tea, c.meses) if prestamo else 0.0
    desg = prestamo * c.desgravamen_mensual
    seg = precio * c.seguro_inmueble_mensual
    return Cuota(
        precio=precio,
        inicial=inicial,
        prestamo=prestamo,
        amortizacion=amort,
        desgravamen=desg,
        seguro_inmueble=seg,
        portes=c.portes,
        total=amort + desg + seg + c.portes,
        tea=c.tea,
        meses=c.meses,
    )


def prestamo_maximo(cuota_max: float, precio: float, c: SupuestosCredito) -> float:
    """Prestamo mas grande cuya primera cuota no pasa de `cuota_max`.

    cuota_max >= P*(f + d) + V*s + portes  =>  P <= (cuota_max - V*s - portes)/(f + d)
    """
    f = factor_cuota(tem_desde_tea(c.tea), c.meses)
    disponible = cuota_max - precio * c.seguro_inmueble_mensual - c.portes
    if disponible <= 0:
        return 0.0
    return disponible / (f + c.desgravamen_mensual)


def inicial_requerida(cuota_max: float, precio: float, c: SupuestosCredito) -> float:
    """Cuota inicial minima (en soles) para que la cuota no pase de `cuota_max`.

    Nunca baja de la inicial minima que exige el banco.
    """
    piso = precio * c.inicial_pct_minima
    necesaria = precio - prestamo_maximo(cuota_max, precio, c) - c.bono_buen_pagador
    return max(piso, necesaria, 0.0)


def precio_maximo(cuota_max: float, inicial: float, c: SupuestosCredito) -> float:
    """Precio de vivienda mas alto alcanzable con una inicial e una cuota tope.

    cuota_max = P*(f+d) + V*s + portes  con  V = inicial + bono + P
    =>  P = (cuota_max - portes - (inicial+bono)*s) / (f + d + s)
    """
    f = factor_cuota(tem_desde_tea(c.tea), c.meses)
    base = inicial + c.bono_buen_pagador
    if base <= 0:
        # Ningun banco financia el 100%: sin inicial no hay compra.
        return 0.0
    num = cuota_max - c.portes - base * c.seguro_inmueble_mensual
    if num <= 0:
        return base
    prestamo = num / (f + c.desgravamen_mensual + c.seguro_inmueble_mensual)
    precio = base + prestamo
    # Respetar la inicial minima exigida por el banco.
    if c.inicial_pct_minima > 0:
        precio = min(precio, base / c.inicial_pct_minima)
    return precio


def cronograma_resumen(precio: float, inicial: float, c: SupuestosCredito) -> dict:
    """Totales del credito completo (util para comparar plazos)."""
    q = cuota_mensual(precio, inicial, c)
    tem = tem_desde_tea(c.tea)
    saldo = q.prestamo
    total_intereses = 0.0
    total_desgravamen = 0.0
    for _ in range(c.meses):
        interes = saldo * tem
        amort_capital = q.amortizacion - interes
        total_intereses += interes
        total_desgravamen += saldo * c.desgravamen_mensual
        saldo = max(saldo - amort_capital, 0.0)
    total_seguro = precio * c.seguro_inmueble_mensual * c.meses
    return {
        "cuota_primer_mes": q.total,
        "cuota_ultimo_mes": q.amortizacion + q.seguro_inmueble + c.portes,
        "total_intereses": total_intereses,
        "total_desgravamen": total_desgravamen,
        "total_seguro_inmueble": total_seguro,
        "total_pagado": q.prestamo + total_intereses + total_desgravamen + total_seguro
        + c.portes * c.meses,
    }
