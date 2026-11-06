"""Conector MCP de TechMaC (stdio, JSON-RPC 2.0).

Seguridad:
- Solo stdio: no abre puertos ni escucha conexiones.
- La red queda BLOQUEADA en este proceso (socket deshabilitado al arrancar).
- No existe ninguna herramienta para aprobar, ejecutar ni enviar órdenes.
  Claude solo puede PROPONER; la aprobación se hace en tu terminal con la
  frase exacta (tm.py approve), que exige una terminal interactiva.
- Toda entrada se valida y todo cambio queda en la auditoría encadenada.
"""

import json
import socket
import sys
import traceback

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_LINE = 1024 * 1024


def _block_network():
    def blocked(*_a, **_k):
        raise PermissionError("TechMaC MCP: la red está deshabilitada en el conector.")
    socket.socket = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


from . import __version__
from . import config as C
from . import service as SV
from . import validate as V
from .ledger import Ledger, RiskBlocked, confirmation_phrase

INSTRUCTIONS = (
    "TechMaC es un laboratorio local de backtesting y un libro de órdenes en papel. No se conecta a ningún broker "
    "y no puede ejecutar órdenes. Reglas: (1) nunca presentes un backtest en muestra como evidencia para invertir; "
    "solo 'evaluate' (walk-forward fuera de muestra) produce un veredicto. (2) Si el veredicto es RECHAZADA, dilo "
    "claramente y no propongas órdenes con esa estrategia. (3) Tú solo puedes PROPONER órdenes; el usuario las aprueba "
    "en su propia terminal con 'python3 techmac/tm.py approve <id>'. Nunca intentes aprobarlas tú. (4) Esto no es "
    "asesoría financiera.")

SYM = {"type": "string", "description": "Ticker, p. ej. SPY, AAPL, BRK-B"}
IV = {"type": "string", "enum": list(V.INTERVALS), "description": "Intervalo de velas"}
STRAT = {"type": "string", "enum": ["orb", "sma_cross", "donchian"]}
DATE = {"type": "string", "description": "AAAA-MM-DD"}

TOOLS = [
    {"name": "data_status",
     "description": "Inventario de datos locales: símbolos, intervalos, sesiones, rango de fechas y huecos.",
     "inputSchema": {"type": "object", "properties": {"symbol": SYM}, "additionalProperties": False}},
    {"name": "list_strategies",
     "description": "Estrategias disponibles, sus parámetros con límites y la rejilla por defecto.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "backtest",
     "description": "Backtest EN MUESTRA con parámetros fijos (exploración). Incluye costos, slippage y gaps. "
                    "No sirve para decidir: para eso usa evaluate.",
     "inputSchema": {"type": "object", "required": ["symbol", "interval", "strategy"], "additionalProperties": False,
                     "properties": {"symbol": SYM, "interval": IV, "strategy": STRAT,
                                    "params": {"type": "object"}, "start": DATE, "end": DATE}}},
    {"name": "evaluate",
     "description": "Evaluación seria: walk-forward fuera de muestra, costos x2, Monte Carlo por bloques y Deflated "
                    "Sharpe. Devuelve un veredicto APROBADA/RECHAZADA y lo guarda con un evaluation_id.",
     "inputSchema": {"type": "object", "required": ["symbol", "interval", "strategy"], "additionalProperties": False,
                     "properties": {"symbol": SYM, "interval": IV, "strategy": STRAT,
                                    "grid": {"type": "object", "description": "{parámetro: [valores]}"},
                                    "train_days": {"type": "integer"}, "test_days": {"type": "integer"},
                                    "start": DATE, "end": DATE}}},
    {"name": "list_evaluations",
     "description": "Últimas evaluaciones guardadas con su veredicto.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_evaluation",
     "description": "Detalle de una evaluación guardada.",
     "inputSchema": {"type": "object", "required": ["evaluation_id"], "additionalProperties": False,
                     "properties": {"evaluation_id": {"type": "integer"}}}},
    {"name": "propose_order",
     "description": "PROPONE una compra en el libro local en papel. Pasa por todos los límites de riesgo y exige una "
                    "evaluación APROBADA del mismo símbolo. No ejecuta nada: el usuario la aprueba en su terminal.",
     "inputSchema": {"type": "object", "required": ["symbol", "qty", "entry", "stop", "evaluation_id"],
                     "additionalProperties": False,
                     "properties": {"symbol": SYM, "qty": {"type": "integer", "minimum": 1},
                                    "entry": {"type": "number"}, "stop": {"type": "number"},
                                    "target": {"type": "number"}, "evaluation_id": {"type": "integer"},
                                    "note": {"type": "string", "maxLength": 500}}}},
    {"name": "ledger_status",
     "description": "Estado del libro: órdenes, P&L realizado, expectativa real vs backtest, límites e interruptor KILL.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "verify_audit",
     "description": "Verifica que la auditoría encadenada por hash no fue alterada.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def _args(a, allowed):
    if not isinstance(a, dict):
        raise V.ValidationError("Los argumentos deben ser un objeto.")
    extra = set(a) - set(allowed)
    if extra:
        raise V.ValidationError("Argumentos no permitidos: %s" % ", ".join(sorted(extra)))
    return a


def call_tool(name, a, h=None):
    if name == "data_status":
        a = _args(a, ["symbol"])
        return SV.data_status(h, a.get("symbol"))
    if name == "list_strategies":
        _args(a, [])
        return SV.list_strategies()
    if name == "backtest":
        a = _args(a, ["symbol", "interval", "strategy", "params", "start", "end"])
        return SV.backtest(h, a.get("symbol"), a.get("interval"), a.get("strategy"), a.get("params") or {},
                           a.get("start"), a.get("end"))
    if name == "evaluate":
        a = _args(a, ["symbol", "interval", "strategy", "grid", "train_days", "test_days", "start", "end"])
        r = SV.evaluate(h, a.get("symbol"), a.get("interval"), a.get("strategy"), a.get("grid"),
                        a.get("train_days"), a.get("test_days"), a.get("start"), a.get("end"), actor="claude-mcp")
        return SV.summarize_evaluation(r)
    if name == "list_evaluations":
        _args(a, [])
        led = Ledger(h)
        try:
            return led.evaluations()
        finally:
            led.close()
    if name == "get_evaluation":
        a = _args(a, ["evaluation_id"])
        return SV.summarize_evaluation(SV.get_evaluation(h, a.get("evaluation_id")))
    if name == "propose_order":
        a = _args(a, ["symbol", "qty", "entry", "stop", "target", "evaluation_id", "note"])
        led = Ledger(h)
        try:
            o = led.propose(a.get("symbol"), a.get("qty"), a.get("entry"), a.get("stop"), a.get("target"),
                            a.get("evaluation_id"), a.get("note", ""), actor="claude-mcp")
        finally:
            led.close()
        return {"order": o,
                "next_step": "Pídele al usuario que la revise y, si quiere, la apruebe EN SU TERMINAL con: "
                             "python3 techmac/tm.py approve %d  (frase: %s). Tú no puedes aprobarla."
                             % (o["id"], confirmation_phrase(o))}
    if name == "ledger_status":
        _args(a, [])
        led = Ledger(h)
        try:
            return led.status()
        finally:
            led.close()
    if name == "verify_audit":
        _args(a, [])
        led = Ledger(h)
        try:
            return led.verify_audit()
        finally:
            led.close()
    raise V.ValidationError("Herramienta desconocida: %s" % name)


def _text(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def handle(msg, h=None):
    """Devuelve la respuesta JSON-RPC (o None para notificaciones)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Solicitud inválida"}}
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None  # notificación (p. ej. notifications/initialized)
    if method == "initialize":
        want = params.get("protocolVersion")
        result = {"protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "TechMaC", "version": __version__},
                  "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            result = {"content": [{"type": "text", "text": _text(call_tool(name, args, h))}], "isError": False}
        except RiskBlocked as e:
            result = {"content": [{"type": "text", "text": _text({"blocked": True, "reasons": e.reasons})}],
                      "isError": True}
        except (V.ValidationError, ValueError, KeyError, TypeError) as e:
            result = {"content": [{"type": "text", "text": "Error: %s" % e}], "isError": True}
        except Exception:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            result = {"content": [{"type": "text", "text": "Error interno de TechMaC (detalle en stderr)."}],
                      "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Método no soportado: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    _block_network()
    C.secure_dir(C.home())
    for line in sys.stdin:
        if len(line) > MAX_LINE:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Mensaje demasiado grande"}}
        else:
            line = line.strip()
            if not line:
                continue
            try:
                resp = handle(json.loads(line))
            except json.JSONDecodeError:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
