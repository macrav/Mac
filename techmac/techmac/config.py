"""Carpeta de datos, permisos y configuración validada."""

import copy
import json
import os
from pathlib import Path

from . import validate as V

# Cada clave: (valor por defecto, mínimo, máximo). Listas y dicts se validan aparte.
DEFAULTS = {
    "account_equity": (10000.0, 100.0, 1e9),
    "max_loss_per_trade_usd": (50.0, 1.0, 1e7),
    "max_daily_loss_usd": (150.0, 1.0, 1e7),
    "max_trades_per_day": (3, 1, 100),
    "max_open_positions": (3, 1, 100),
    "min_reward_risk": (1.0, 0.0, 20.0),
    "max_position_pct": (50.0, 1.0, 100.0),
    "require_validated_strategy": (True, None, None),
    "max_evaluation_age_days": (90, 1, 3650),
    "proposal_ttl_minutes": (30, 1, 1440),
    "allowed_symbols": ([], None, None),
    "costs": ({
        "commission_per_share": (0.005, 0.0, 1.0),
        "commission_min": (1.0, 0.0, 100.0),
        "slippage_bps": (5.0, 0.0, 500.0),
        "spread_bps": (2.0, 0.0, 500.0),
    }, None, None),
    "backtest": ({
        "initial_equity": (10000.0, 100.0, 1e9),
        "risk_pct": (0.5, 0.01, 10.0),
        "max_position_pct": (100.0, 1.0, 100.0),
        "flat_by": ("15:55", None, None),
    }, None, None),
    "criteria": ({
        "min_oos_trades": (100, 10, 100000),
        "min_profit_factor": (1.2, 1.0, 10.0),
        "min_dsr": (0.95, 0.5, 0.9999),
        "max_dd_p95_pct": (20.0, 1.0, 100.0),
        "require_beat_buy_hold": (True, None, None),
    }, None, None),
}


def _defaults(spec):
    out = {}
    for k, (val, _lo, _hi) in spec.items():
        out[k] = _defaults(val) if isinstance(val, dict) else copy.deepcopy(val)
    return out


def _check(spec, data, prefix=""):
    if not isinstance(data, dict):
        raise V.ValidationError("%s debe ser un objeto." % (prefix or "config"))
    unknown = set(data) - set(spec)
    if unknown:
        raise V.ValidationError("Claves desconocidas en config: %s" % ", ".join(sorted(prefix + k for k in unknown)))
    out = {}
    for k, (val, lo, hi) in spec.items():
        name = prefix + k
        if k not in data:
            out[k] = _defaults(val) if isinstance(val, dict) else copy.deepcopy(val)
            continue
        x = data[k]
        if isinstance(val, dict):
            out[k] = _check(val, x, name + ".")
        elif isinstance(val, bool):
            if not isinstance(x, bool):
                raise V.ValidationError("%s debe ser true/false." % name)
            out[k] = x
        elif isinstance(val, list):
            if not isinstance(x, list) or len(x) > 5000:
                raise V.ValidationError("%s debe ser una lista." % name)
            out[k] = [V.symbol(s) for s in x]
        elif isinstance(val, str):
            V.hhmm(x, name)
            out[k] = x
        else:
            out[k] = V.number(x, name, lo, hi, integer=isinstance(val, int))
    return out


def home():
    return Path(os.environ.get("TECHMAC_HOME") or (Path.home() / ".techmac")).expanduser().resolve()


def secure_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def secure_file(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def config_path(h=None):
    return Path(h or home()) / "config.json"


def load(h=None):
    p = config_path(h)
    if not p.exists():
        return _defaults(DEFAULTS)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _check(DEFAULTS, data)


def init(h=None):
    h = secure_dir(h or home())
    p = config_path(h)
    created = False
    if not p.exists():
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_defaults(DEFAULTS), f, indent=2, ensure_ascii=False)
        created = True
    secure_file(p)
    return h, created


def kill_switch_on(h=None):
    return (Path(h or home()) / "KILL").exists()
