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


def _print_portfolio(r):
    o, b, ew = r["out_of_sample"], r["benchmark_buy_and_hold"], r["equal_weight_same_assets"]
    st = r["setup"]
    print("\n=== Portafolio %s | %s | evaluación #%s ===" % (",".join(st["symbols"]), r["strategy"], r.get("evaluation_id")))
    print("Fuera de muestra %s a %s (%d ventanas, %d combinaciones)" % (o["period"][0], o["period"][1],
                                                                       len(r["folds"]), st["combos_tested"]))
    fmt = "  %-26s CAGR %6s %%  Sharpe %6s  Máx. caída %6s %%"
    print(fmt % ("Estrategia", o["equity"]["cagr_pct"], o["equity"]["sharpe_annual"], o["equity"]["max_drawdown_pct"]))
    print(fmt % ("Con costos x2", r["stress_costs_x2"]["cagr_pct"], r["stress_costs_x2"]["sharpe_annual"],
                 r["stress_costs_x2"]["max_drawdown_pct"]))
    print(fmt % ("Comprar y mantener " + st["benchmark"], b["cagr_pct"], b["sharpe_annual"], b["max_drawdown_pct"]))
    print(fmt % ("Mismo peso, mismos activos", ew["cagr_pct"], ew["sharpe_annual"], ew["max_drawdown_pct"]))
    print("  Rotación: %s veces el capital al año | DSR %s" % (o["turnover_per_year"], o["dsr"]))
    w = r["current_target_weights"]
    print("Pesos que tocaría tener hoy (%s): %s, efectivo %s" % (w["as_of"], w["weights"], w["cash"]))
    v = r["verdict"]
    print("\nVEREDICTO: %s" % v["label"])
    for c in v["checks"]:
        print("  [%s] %-36s %s (regla %s)" % ("OK" if c["pass"] else "NO", c["check"], c["value"], c["rule"]))
    print(v["meaning"])


def _print_ranking(r):
    print("\nRanking (el DSR de cada fila cuenta las %d combinaciones probadas en total)\n" % r["total_trials_counted"])
    print("%-6s %-14s %-5s %8s %7s %8s %7s %7s %6s  %s" % ("Símbolo", "Estrategia", "Eval", "Oper.", "Exp.R",
                                                          "Sharpe", "B&H", "MáxDD", "DSR", "Veredicto"))
    for x in r["rows"]:
        if "error" in x:
            print("%-6s %-14s  error: %s" % (x["symbol"], x["strategy"], x["error"]))
            continue
        print("%-7s %-14s #%-4s %8s %7s %8s %7s %7s %6s  %s" % (
            x["symbol"], x["strategy"], x["evaluation_id"], x["trades"], x["expectancy_r"], x["sharpe"],
            x["buy_hold_sharpe"], x["max_dd_pct"], x["dsr"], x["verdict"]))


def _print_goal(r):
    print("\nFuente: %s, %d meses de historia, %d simulaciones" % (r["source"], r["months_of_history"], r["simulations"]))
    print("Capital $%s + $%s/mes, meta $%s, horizonte %d años\n" % (
        format(r["capital"], ",.0f"), format(r["monthly_contribution"], ",.0f"), format(r["target"], ",.0f"),
        r["horizon_years"]))
    print("%-7s %12s %10s %10s %10s %10s %14s" % ("Apalanc.", "Años (med.)", "P<=10a", "P<=20a", "P quiebra",
                                                 "P caída50", "Final mediano"))
    for x in r["results"]:
        print("%-7s %12s %9s%% %9s%% %9s%% %9s%% %14s" % (
            "%sx" % x["leverage"], x["median_years_to_target"] if x["median_years_to_target"] is not None else "nunca*",
            x["prob_target_10y_pct"], x["prob_target_20y_pct"], x["prob_ruin_pct"], x["prob_drop_50pct"],
            format(x["final_median"], ",.0f")))
    print("\n* menos de la mitad de las simulaciones llega a la meta en el horizonte.")
    print(r["warning"])


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

    sub.add_parser("allocations", help="estrategias de portafolio multi-activo")
    po = sub.add_parser("portfolio", help="evalúa un portafolio global con rebalanceo mensual (walk-forward)")
    po.add_argument("symbols", nargs="+", help="activos, incluido el seguro, p. ej. SPY EFA EEM GLD IEF SHY")
    po.add_argument("--strategy", default="dual_momentum")
    po.add_argument("--safe", help="activo seguro (debe estar en la lista), p. ej. SHY")
    po.add_argument("--benchmark", help="por defecto el primer símbolo")
    po.add_argument("--grid")
    po.add_argument("--train-years", type=int, default=5)
    po.add_argument("--test-years", type=int, default=1)
    po.add_argument("--target-vol", type=float, default=0.0, help="volatilidad anual objetivo en %%, 0 = apagado")
    po.add_argument("--max-leverage", type=float, default=1.0)

    rk = sub.add_parser("ranking", help="evalúa todas las estrategias diarias en varios símbolos y las ordena")
    rk.add_argument("symbols", nargs="+")
    rk.add_argument("--strategies", help="lista separada por comas (por defecto todas las diarias)")

    g = sub.add_parser("goal", help="¿cuánto tardo en llegar a mi meta y cuál es el riesgo de quebrar?")
    src = g.add_mutually_exclusive_group(required=True)
    src.add_argument("--evaluation", type=int, help="usar los retornos fuera de muestra de esta evaluación")
    src.add_argument("--symbol", help="usar comprar y mantener este activo")
    g.add_argument("--capital", type=float, default=10000)
    g.add_argument("--monthly", type=float, default=0, help="aporte mensual")
    g.add_argument("--target", type=float, default=1_000_000)
    g.add_argument("--years", type=int, default=40)
    g.add_argument("--leverage", default="1,1.5,2,3")

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

    if a.cmd == "allocations":
        _out(SV.list_allocations(), a.json)
        return 0
    if a.cmd == "portfolio":
        r = SV.evaluate_portfolio(h, a.symbols, a.strategy, a.safe, a.benchmark,
                                  json.loads(a.grid) if a.grid else None, a.train_years, a.test_years,
                                  a.target_vol, a.max_leverage, actor="humano-terminal")
        if a.json:
            _out(r, True)
        else:
            _print_portfolio(r)
        return 0
    if a.cmd == "ranking":
        strategies = [x.strip() for x in a.strategies.split(",")] if a.strategies else None
        r = SV.ranking(h, a.symbols, strategies, actor="humano-terminal")
        if a.json:
            _out(r, True)
        else:
            _print_ranking(r)
        return 0
    if a.cmd == "goal":
        levs = [float(x) for x in a.leverage.split(",") if x.strip()]
        r = SV.goal(h, a.evaluation, a.symbol, a.capital, a.monthly, a.target, a.years, levs)
        if a.json:
            _out(r, True)
        else:
            _print_goal(r)
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
