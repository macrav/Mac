"""Hora de Nueva York sin dependencias (reglas de horario de verano de EE. UU. desde 2007)."""

import datetime as dt

UTC = dt.timezone.utc


def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def ny_offset_hours(utc_dt):
    """-4 en horario de verano, -5 en invierno."""
    y = utc_dt.year
    start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(7), UTC)   # 2:00 EST
    end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(6), UTC)    # 2:00 EDT
    return -4 if start <= utc_dt < end else -5


def to_ny(ts):
    """Epoch UTC (segundos) -> datetime ingenuo en hora de Nueva York."""
    utc = dt.datetime.fromtimestamp(ts, UTC)
    return (utc + dt.timedelta(hours=ny_offset_hours(utc))).replace(tzinfo=None)


def ny_to_epoch(local):
    """datetime ingenuo en hora de Nueva York -> epoch UTC."""
    for off in (-4, -5):
        utc = (local - dt.timedelta(hours=off)).replace(tzinfo=UTC)
        if ny_offset_hours(utc) == off:
            return int(utc.timestamp())
    # hora inexistente (salto de primavera): usa horario de invierno
    return int((local + dt.timedelta(hours=5)).replace(tzinfo=UTC).timestamp())


def ny_now():
    return to_ny(dt.datetime.now(UTC).timestamp())
