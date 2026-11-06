"""Línea de comandos de TechMaC.  Uso: python3 techmac/tm.py <comando> --help"""

import argparse
import json
import sys
from pathlib import Path

from . import config as C
from . import service as SV
from . import validate as V
from .ledger import Ledger, RiskBlocked, confirmation_phrase
from .store import Store, parse_csv


def _out(obj, as_json):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        _pretty(obj)


def _pretty(obj, indent=0):
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                print("%s%s:" % (pad, k))
                _pretty(v, indent + 1)
            else:
                print("%s%s: %s" % (pad, k, v))
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict):
                print(pad + "-")
                _pretty(v, indent + 1)
            else:
                print("%s- %s" % (pad, v))
    else:
        print(pad + str(obj))


def _require_tty(what):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("TechMaC: '%s' solo se puede hacer en tu propia terminal interactiva. Ni Claude ni ningún script "
                 "pueden hacerlo por ti." % what)


def _print_verdict(r):
    v = r["verdict"]
    print("\n=== %s %s %s | evaluación #%s ===" % (r["symbol"], r["interval"], r["strategy"], r.get("evaluation_id")))
    print("Datos: %s a %s (%d sesiones), %d combinaciones probadas, %d ventanas walk-forward"
          % (r["data"]["first"], r["data"]["last"], r["data"]["sessions"], r["setup"]["combos_tested"],
             len(r["folds"])))
    t = r["out_of_sample"]["trades"]
    eq = r["out_of_sample"]["equity"]
    if t.get("trades"):
        print("Fuera de muestra: %d operaciones, acierto %.1f %%, expectativa %.3f R (IC95 %s), PF %s"
              % (t["trades"], t["win_rate_pct"], t["expectancy_r"], t["expectancy_r_ci95"], t["profit_factor"]))
        print("Capital: retorno %s %%, CAGR %s %%, Sharpe %s, máx. drawdown %s %%  | Buy & hold: %s"
              % (eq.get("total_return_pct"), eq.get("cagr_pct"), eq.get("sharpe_annual"),
                 eq.get("max_drawdown_pct"), r["buy_and_hold_same_period"]))
    else:
        print("Fuera de muestra: 0 operaciones.")
    print("\nVEREDICTO: %s" % v["label"])
    for c in v["checks"]:
        print("  [%s] %-40s %s (regla %s)" % ("OK" if c["pass"] else "NO", c["check"], c["value"], c["rule"]))
    print(v["meaning"])


def main(argv=None):
    p = argparse.ArgumentParser(prog="tm.py", description="TechMaC: backtesting serio y libro en papel, 100 % local.")
    p.add_argument("--json", action="store_true", help="salida JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea ~/.techmac (o $TECHMAC_HOME) con permisos privados y config.json")

    f = sub.add_parser("fetch", help="descarga datos públicos (Yahoo/Stooq) a tu almacén local")
    f.add_argument("symbols", nargs="+")
    f.add_argument("--interval", default="1d")
    f.add_argument("--source", choices=["yahoo", "stooq"], default="yahoo")

    ic = sub.add_parser("import-csv", help="importa velas desde un CSV propio (recomendado para datos de calidad)")
    ic.add_argument("path")
    ic.add_argument("--symbol", required=True)
    ic.add_argument("--interval", required=True)
    ic.add_argument("--tz", default="NY", choices=["NY", "UTC"], help="zona de las fechas sin zona")
    ic.add_argument("--source", default="csv")

    d = sub.add_parser("data", help="inventario de datos locales")
    d.add_argument("--symbol")

    sub.add_parser("strategies", help="estrategias y parámetros")

    for name, hlp in (("backtest", "backtest en muestra (exploración)"),
                      ("evaluate", "walk-forward + Monte Carlo + DSR + veredicto")):
        b = sub.add_parser(name, help=hlp)
        b.add_argument("symbol")
        b.add_argument("--interval", default="1d")
        b.add_argument("--strategy", default="sma_cross")
        b.add_argument("--start")
        b.add_argument("--end")
        if name == "backtest":
            b.add_argument("--params", default="{}", help='JSON, p. ej. \'{"fast": 20, "slow": 100}\'')
        else:
            b.add_argument("--grid", help='JSON, p. ej. \'{"fast": [10, 20], "slow": [100, 200]}\'')
            b.add_argument("--train-days", type=int)
            b.add_argument("--test-days", type=int)

    pr = sub.add_parser("propose", help="propone una compra (pasa por los límites de riesgo)")
    pr.add_argument("symbol")
    pr.add_argument("--qty", type=int, required=True)
    pr.add_argument("--entry", type=float, required=True)
    pr.add_argument("--stop", type=float, required=True)
    pr.add_argument("--target", type=float)
    pr.add_argument("--evaluation", type=int)
    pr.add_argument("--note", default="")

    ip = sub.add_parser("import-plan", help="propone las órdenes de trader/orders.json de day-trader-skill")
    ip.add_argument("path")
    ip.add_argument("--evaluation", type=int)

    for name, hlp in (("approve", "aprueba una orden (solo terminal interactiva + frase exacta)"),
                      ("reject", "rechaza una orden")):
        a = sub.add_parser(name, help=hlp)
        a.add_argument("order_id", type=int)

    rf = sub.add_parser("record-fill", help="registra a qué precio la ejecutaste TÚ en tu broker")
    rf.add_argument("order_id", type=int)
    rf.add_argument("--price", type=float, required=True)
    rf.add_argument("--qty", type=int)
    rx = sub.add_parser("record-exit", help="registra la salida y el P&L")
    rx.add_argument("order_id", type=int)
    rx.add_argument("--price", type=float, required=True)

    sub.add_parser("ledger", help="estado del libro y límites")
    au = sub.add_parser("audit", help="verifica la auditoría encadenada")
    au.add_argument("--tail", type=int, default=0)
    k = sub.add_parser("kill", help="interruptor de emergencia: on bloquea toda orden nueva")
    k.add_argument("state", choices=["on", "off"])

    a = p.parse_args(argv)
    h = C.home()
    try:
        return _dispatch(a, h)
    except RiskBlocked as e:
        print("BLOQUEADO:")
        for r in e.reasons:
            print("  - " + r)
        return 2
    except (V.ValidationError, ValueError, OSError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1


def _dispatch(a, h):
    if a.cmd == "init":
        home, created = C.init(h)
        print("Carpeta TechMaC: %s (permisos 700). config.json %s." % (home, "creado" if created else "ya existía"))
        print("Edita config.json para tus límites reales antes de proponer órdenes.")
        return 0

    if a.cmd == "fetch":
        from . import fetch as F  # único import con red, solo aquí
        st = Store(h)
        try:
            for sym in a.symbols:
                try:
                    if a.source == "stooq":
                        if a.interval != "1d":
                            raise V.ValidationError("Stooq solo da velas diarias.")
                        bars, raw = F.stooq(sym)
                    else:
                        bars, raw = F.yahoo(sym, a.interval)
                    good, bad = st.upsert(sym, a.interval, bars, a.source, raw)
                    print("%s %s: %d velas guardadas, %d rechazadas por integridad." % (sym.upper(), a.interval, good, bad))
                except (F.FetchError, V.ValidationError) as e:
                    print("%s: %s" % (sym, e), file=sys.stderr)
        finally:
            st.close()
        return 0

    if a.cmd == "import-csv":
        raw = Path(a.path).read_bytes()
        bars, bad_rows = parse_csv(raw, V.interval(a.interval), a.tz)
        st = Store(h)
        try:
            good, bad = st.upsert(a.symbol, a.interval, bars, V.text(a.source, "source", 40), raw)
        finally:
            st.close()
        print("%d velas importadas, %d filas ilegibles, %d rechazadas por integridad." % (good, bad_rows, bad))
        return 0

    if a.cmd == "data":
        _out(SV.data_status(h, a.symbol), a.json)
        return 0
    if a.cmd == "strategies":
        _out(SV.list_strategies(), a.json)
        return 0
    if a.cmd == "backtest":
        _out(SV.backtest(h, a.symbol, a.interval, a.strategy, json.loads(a.params), a.start, a.end), a.json)
        return 0
    if a.cmd == "evaluate":
        r = SV.evaluate(h, a.symbol, a.interval, a.strategy, json.loads(a.grid) if a.grid else None,
                        a.train_days, a.test_days, a.start, a.end, actor="humano-terminal")
        if a.json:
            _out(r, True)
        else:
            _print_verdict(r)
        return 0

    led = Ledger(h)
    try:
        if a.cmd == "propose":
            o = led.propose(a.symbol, a.qty, a.entry, a.stop, a.target, a.evaluation, a.note, "humano-terminal")
            _out(o, a.json)
            print("\nPara aprobarla: python3 techmac/tm.py approve %d" % o["id"])
        elif a.cmd == "import-plan":
            _out(SV.import_plan_orders(h, a.path, a.evaluation), a.json)
        elif a.cmd == "approve":
            _require_tty("approve")
            o = led.order(a.order_id)
            if o is None:
                raise RiskBlocked(["No existe la orden #%d." % a.order_id])
            print("\nTICKET #%d  (TechMaC no envía órdenes: si apruebas, la ejecutas TÚ en tu broker)" % o["id"])
            print("  Comprar %d %s ~%.2f | stop %.2f | objetivo %s | pérdida al stop $%.2f | evaluación #%s"
                  % (o["qty"], o["symbol"], o["entry"], o["stop"], o["target"], o["risk_usd"], o["evaluation_id"]))
            phrase = confirmation_phrase(o)
            print("\nPara aprobar escribe exactamente:  %s" % phrase)
            typed = input("> ")
            o = led.approve(a.order_id, typed)
            print("Aprobada. Cuando la ejecutes, registra el precio: python3 techmac/tm.py record-fill %d --price X"
                  % o["id"])
        elif a.cmd == "reject":
            _out(led.reject(a.order_id), a.json)
        elif a.cmd == "record-fill":
            _require_tty("record-fill")
            _out(led.record_fill(a.order_id, a.price, a.qty), a.json)
        elif a.cmd == "record-exit":
            _require_tty("record-exit")
            _out(led.record_exit(a.order_id, a.price), a.json)
        elif a.cmd == "ledger":
            _out(led.status(), a.json)
        elif a.cmd == "audit":
            r = led.verify_audit()
            _out(r, a.json)
            if a.tail:
                _out(led.audit_tail(a.tail), a.json)
            if not r["ok"]:
                return 3
        elif a.cmd == "kill":
            path = Path(led.home) / "KILL"
            if a.state == "on":
                path.write_text("activado\n")
                C.secure_file(path)
                led.conn.execute("BEGIN IMMEDIATE")
                led._audit("humano-terminal", "kill_on", {})
                led.conn.execute("COMMIT")
                print("KILL activado: no se puede proponer ni aprobar ninguna orden.")
            else:
                _require_tty("kill off")
                if path.exists():
                    path.unlink()
                led.conn.execute("BEGIN IMMEDIATE")
                led._audit("humano-terminal", "kill_off", {})
                led.conn.execute("COMMIT")
                print("KILL desactivado.")
    finally:
        led.close()
    return 0
