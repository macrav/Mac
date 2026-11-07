"""Asesor financiero de orientación (educativo) para Perú.

No reemplaza a un asesor autorizado por la SMV. Ordena tus finanzas con reglas prudentes y
conocidas: primero deudas caras, luego fondo de emergencia, luego metas cortas sin riesgo y, solo
después, inversión de largo plazo según tu perfil. Nunca recomienda apalancamiento ni trading con
dinero que no haya pasado por la evaluación de TechMaC.
"""

import json
from pathlib import Path

from . import config as C
from . import peru as P
from . import validate as V

QUESTIONS = [
    {"id": "objetivo", "text": "¿Cuál es tu objetivo principal con este dinero?",
     "options": ["Protegerlo, no perder nada", "Que genere algo más que el banco", "Crecer de forma moderada",
                 "Crecer lo máximo, aceptando riesgo alto"]},
    {"id": "horizonte", "text": "¿Cuándo vas a necesitar este dinero?",
     "options": ["En menos de 1 año", "En 1 a 3 años", "En 3 a 5 años", "En 5 a 10 años", "En más de 10 años"]},
    {"id": "reaccion", "text": "Si tu inversión cae 20 % en un mes, ¿qué haces?",
     "options": ["Vendo todo", "Vendo una parte", "Espero sin hacer nada", "Aprovecho y compro más"]},
    {"id": "perdida_max", "text": "¿Cuánto podrías ver bajar tu saldo en un año sin vender ni perder el sueño?",
     "options": ["0 %: no acepto ninguna baja", "Hasta 5 %", "Hasta 10 %", "Hasta 20 %", "30 % o más"]},
    {"id": "ingresos", "text": "¿Qué tan estables son tus ingresos?",
     "options": ["Muy inestables", "Variables", "Estables", "Muy estables y con respaldo"]},
    {"id": "experiencia", "text": "¿Qué has invertido antes?",
     "options": ["Nada, solo ahorro", "Depósitos o fondos mutuos", "Acciones o ETFs", "Varios años invirtiendo"]},
    {"id": "dependencia", "text": "Si perdieras este dinero, ¿cuánto afectaría tu vida?",
     "options": ["Mucho", "Algo", "Poco"]},
]

PROFILES = {
    "conservador_estricto": {
        "label": "Conservador estricto",
        "summary": "No aceptas bajas de saldo. Solo instrumentos con capital protegido.",
        "allocation": {"Depósitos con FSD y ahorro sin riesgo": 100},
    },
    "conservador": {
        "label": "Conservador",
        "summary": "Aceptas bajas pequeñas y temporales a cambio de algo más de rendimiento.",
        "allocation": {"Depósitos con FSD": 60, "Fondos de deuda de corto plazo / AFP Fondo 0-1": 30,
                       "Renta variable global diversificada": 10},
    },
    "moderado": {
        "label": "Moderado",
        "summary": "Aceptas caídas de 10 % a 20 % en años malos si el horizonte es largo.",
        "allocation": {"Depósitos con FSD": 30, "Renta fija y fondos de deuda": 30,
                       "Renta variable global diversificada": 40},
    },
    "crecimiento": {
        "label": "Crecimiento",
        "summary": "Horizonte largo y tolerancia a caídas de 30 % o más sin vender.",
        "allocation": {"Depósitos con FSD": 15, "Renta fija y fondos de deuda": 25,
                       "Renta variable global diversificada": 60},
    },
}

ORDER = ["conservador_estricto", "conservador", "moderado", "crecimiento"]

# Supuestos de proyección (nominales, en soles); se muestran siempre como supuestos.
ASSUMPTIONS = {"Depósitos con FSD y ahorro sin riesgo": 4.0, "Depósitos con FSD": 4.0,
               "Fondos de deuda de corto plazo / AFP Fondo 0-1": 4.5, "Renta fija y fondos de deuda": 5.0,
               "Renta variable global diversificada": 7.5}


def _path(h=None):
    return Path(h or C.home()) / "perfil.json"


def score_profile(answers):
    """answers: {id: índice de opción}. Devuelve el perfil con reglas de protección."""
    if not isinstance(answers, dict):
        raise V.ValidationError("Las respuestas deben ser un objeto {pregunta: índice}.")
    clean = {}
    for q in QUESTIONS:
        if q["id"] not in answers:
            raise V.ValidationError("Falta responder: %s" % q["text"])
        clean[q["id"]] = int(V.number(answers[q["id"]], q["id"], 0, len(q["options"]) - 1, True))
    extra = set(answers) - set(clean)
    if extra:
        raise V.ValidationError("Preguntas desconocidas: %s" % ", ".join(sorted(extra)))
    pts = sum(clean.values())
    maxpts = sum(len(q["options"]) - 1 for q in QUESTIONS)
    pct = pts / maxpts
    idx = 0 if pct < 0.3 else 1 if pct < 0.5 else 2 if pct < 0.75 else 3
    reasons = []
    # Reglas que mandan sobre el puntaje: la persona más prudente de ti decide.
    if clean["perdida_max"] == 0 or clean["objetivo"] == 0:
        idx, reasons = 0, reasons + ["No aceptas ninguna baja: solo capital protegido."]
    if clean["reaccion"] == 0 and idx > 1:
        idx, reasons = 1, reasons + ["Venderías todo ante una caída: más riesgo te haría perder de verdad."]
    if clean["horizonte"] <= 1 and idx > 0:
        idx, reasons = 0, reasons + ["Necesitas el dinero en menos de 3 años: no debe estar en bolsa."]
    elif clean["horizonte"] == 2 and idx > 1:
        idx, reasons = 1, reasons + ["Horizonte de 3 a 5 años: como máximo, perfil conservador."]
    if clean["perdida_max"] <= 2 and idx > 2:
        idx, reasons = 2, reasons + ["Toleras como máximo 10 % de baja: perfil moderado como tope."]
    if clean["dependencia"] == 0 and idx > 1:
        idx, reasons = 1, reasons + ["Perder este dinero te afectaría mucho: perfil conservador como tope."]
    key = ORDER[idx]
    return {"answers": clean, "score_pct": round(100 * pct), "profile": key, "label": PROFILES[key]["label"],
            "summary": PROFILES[key]["summary"], "caps_applied": reasons}


def _finances(f):
    if not isinstance(f, dict):
        raise V.ValidationError("Las finanzas deben ser un objeto.")
    allowed = {"moneda", "ingreso_mensual", "gastos_mensuales", "ahorro_mensual", "ahorros_actuales",
               "ahorros_por_entidad", "deudas", "dependientes", "tipo_trabajo", "aporta_afp", "metas"}
    extra = set(f) - allowed
    if extra:
        raise V.ValidationError("Campos desconocidos: %s" % ", ".join(sorted(extra)))
    out = {
        "moneda": f.get("moneda", "PEN"),
        "ingreso_mensual": V.number(f.get("ingreso_mensual", 0), "ingreso_mensual", 0, 1e8),
        "gastos_mensuales": V.number(f.get("gastos_mensuales", 0), "gastos_mensuales", 0, 1e8),
        "ahorro_mensual": V.number(f.get("ahorro_mensual", 0), "ahorro_mensual", 0, 1e8),
        "ahorros_actuales": V.number(f.get("ahorros_actuales", 0), "ahorros_actuales", 0, 1e10),
        "dependientes": int(V.number(f.get("dependientes", 0), "dependientes", 0, 20, True)),
        "tipo_trabajo": f.get("tipo_trabajo", "dependiente"),
        "aporta_afp": bool(f.get("aporta_afp", False)),
        "ahorros_por_entidad": {}, "deudas": [], "metas": [],
    }
    if out["moneda"] not in ("PEN", "USD"):
        raise V.ValidationError("moneda debe ser PEN o USD.")
    if out["tipo_trabajo"] not in ("dependiente", "independiente"):
        raise V.ValidationError("tipo_trabajo debe ser dependiente o independiente.")
    for name, amt in (f.get("ahorros_por_entidad") or {}).items():
        out["ahorros_por_entidad"][V.text(name, "entidad", 60)] = V.number(amt, "monto", 0, 1e10)
    for d in (f.get("deudas") or [])[:30]:
        out["deudas"].append({"nombre": V.text(d.get("nombre", "deuda"), "nombre", 60),
                              "saldo": V.number(d.get("saldo"), "saldo", 0, 1e10),
                              "tea_pct": V.number(d.get("tea_pct"), "tea_pct", 0, 1000),
                              "cuota": V.number(d.get("cuota", 0), "cuota", 0, 1e8)})
    for m in (f.get("metas") or [])[:20]:
        out["metas"].append({"nombre": V.text(m.get("nombre", "meta"), "nombre", 80),
                             "monto": V.number(m.get("monto"), "monto", 0, 1e10),
                             "anios": V.number(m.get("anios"), "anios", 0.1, 60)})
    return out


def save_profile(h, answers, finances):
    prof = score_profile(answers)
    fin = _finances(finances)
    doc = {"profile": prof, "finances": fin}
    home = C.secure_dir(h or C.home())
    p = _path(home)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    C.secure_file(p)
    return doc


def load_profile(h=None):
    p = _path(h)
    if not p.exists():
        raise V.ValidationError("Aún no hay perfil. Responde el cuestionario (tm.py perfil o advisor_questions).")
    return json.loads(p.read_text(encoding="utf-8"))


def _fv(monthly, years, rate_pct, start=0.0):
    r = rate_pct / 100 / 12
    bal = start
    for _ in range(int(round(years * 12))):
        bal = bal * (1 + r) + monthly
    return bal


def _months_to(gap, monthly):
    return None if monthly <= 0 else max(0, int(-(-gap // monthly)))


def build_plan(doc, usd_pen=None):
    prof, f = doc["profile"], doc["finances"]
    cur = "S/" if f["moneda"] == "PEN" else "US$"
    fsd = P.FACTS["fsd_limit_pen"]["value"]
    fsd_cur = fsd if f["moneda"] == "PEN" else (fsd / usd_pen if usd_pen else None)
    steps, alerts = [], []
    save = f["ahorro_mensual"]
    savings = f["ahorros_actuales"]
    expenses = f["gastos_mensuales"]

    # 0) Coherencia del presupuesto
    if f["ingreso_mensual"] and expenses and f["ingreso_mensual"] - expenses < save:
        alerts.append("Tu ingreso menos tus gastos (%s %.0f) es menor que el ahorro mensual que indicas (%s %.0f). "
                      "Revisa tus números: el plan asume que de verdad puedes ahorrar eso."
                      % (cur, f["ingreso_mensual"] - expenses, cur, save))

    # 1) Deudas caras (método avalancha: primero la de mayor tasa)
    expensive = sorted([d for d in f["deudas"] if d["tea_pct"] >= 15], key=lambda d: -d["tea_pct"])
    if expensive:
        total = sum(d["saldo"] for d in expensive)
        steps.append({
            "step": "Pagar deudas caras",
            "why": "Cada sol o dólar que pagas a una deuda de %.0f %% TEA te 'rinde' %.0f %% seguro, más que cualquier "
                   "inversión legítima. %s" % (expensive[0]["tea_pct"], expensive[0]["tea_pct"],
                                                P.FACTS["consumer_credit"]["text"]),
            "how": ["Mantén las cuotas mínimas de todas y pon todo el ahorro extra en: " +
                    ", ".join("%s (%.0f %% TEA, %s %.0f)" % (d["nombre"], d["tea_pct"], cur, d["saldo"])
                              for d in expensive),
                    "No uses la tarjeta para gastos que no puedas pagar completos ese mes.",
                    "Pregunta por compra de deuda a una tasa menor solo si baja de verdad el costo total (TCEA)."],
            "months": _months_to(total, save)})

    # 2) Fondo de emergencia
    months_target = 9 if f["tipo_trabajo"] == "independiente" else 6
    if f["dependientes"]:
        months_target += 3
    target = months_target * expenses if expenses else None
    if target:
        gap = max(0.0, target - savings)
        steps.append({
            "step": "Fondo de emergencia de %d meses de gastos (%s %.0f)" % (months_target, cur, target),
            "why": "Evita endeudarte o vender inversiones en mal momento ante un imprevisto (salud, trabajo).",
            "how": ["Cuenta de ahorro o depósito a plazo corto en un banco o caja supervisado por la SBS, "
                    "cubierto por el FSD.",
                    "Que sea fácil de retirar en días, no en meses.",
                    "Ya tienes %s %.0f; te faltan %s %.0f." % (cur, savings, cur, gap)],
            "months": _months_to(gap, save) if gap else 0})
    else:
        alerts.append("Sin tus gastos mensuales no puedo calcular el fondo de emergencia.")

    # 3) Metas de corto plazo
    for m in f["metas"]:
        if m["anios"] < 3:
            steps.append({"step": "Meta de corto plazo: %s (%s %.0f en %.1f años)" % (m["nombre"], cur, m["monto"], m["anios"]),
                          "why": "Dinero que necesitas en menos de 3 años no debe estar en bolsa.",
                          "how": ["Depósito a plazo con FSD al plazo de la meta.",
                                  "Aporte mensual necesario aprox.: %s %.0f" % (cur, m["monto"] / (m["anios"] * 12))],
                          "months": None})

    # 4) Largo plazo según perfil
    alloc = PROFILES[prof["profile"]]["allocation"]
    how = ["%d %% en %s" % (pct, name) for name, pct in alloc.items()]
    if prof["profile"] == "conservador_estricto":
        how += ["Reparte entre entidades para que ningún saldo pase el límite del FSD (S/ %s por entidad)." % format(fsd, ","),
                "Compara la TREA vigente en el portal de la SBS. Las cajas y financieras supervisadas suelen pagar "
                "más que los bancos grandes y tienen la misma cobertura del FSD.",
                "Escalera de depósitos: divide en depósitos a 3, 6, 9 y 12 meses para tener liquidez cada trimestre.",
                "Revisa que el rendimiento supere la inflación (%.1f %% a septiembre de 2026); si no, pierdes poder de "
                "compra aunque tu saldo no baje." % P.FACTS["inflation_pct"]["value"]]
    else:
        how += ["Renta variable solo con fondos o ETFs amplios y diversificados (mundo, no una sola acción), "
                "comprados en una SAB autorizada por la SMV o un fondo mutuo supervisado.",
                "Compra cada mes la misma cantidad (promedio de costo) y rebalancea una vez al año.",
                "Nada de apalancamiento, forex, CFD ni trading con este dinero."]
    steps.append({"step": "Inversión de largo plazo (perfil %s)" % prof["label"],
                  "why": PROFILES[prof["profile"]]["summary"], "how": how, "months": None})

    # 5) Jubilación
    if f["tipo_trabajo"] == "independiente" and not f["aporta_afp"]:
        steps.append({"step": "Pensar en tu jubilación",
                      "why": P.FACTS["independent_workers_pension"]["text"],
                      "how": ["Considera aportes voluntarios a la AFP o a la ONP; si tu perfil es conservador, Fondo 0 o 1.",
                              P.FACTS["afp_voluntary"]["text"]], "months": None})

    # Alertas por saldos sobre el FSD
    for ent, amt in f["ahorros_por_entidad"].items():
        if fsd_cur and amt > fsd_cur:
            alerts.append("En %s tienes %s %.0f, más que la cobertura del FSD (aprox. %s %.0f). Mueve el exceso "
                          "a otra entidad." % (ent, cur, amt, cur, fsd_cur))

    alerts.append(P.FACTS["deposit_interest_tax"]["text"])
    if prof["profile"] != "conservador_estricto":
        alerts.append(P.FACTS["capital_gains_tax"]["text"])
        alerts.append(P.FACTS["us_estate_tax"]["text"])

    # Proyección (supuestos explícitos, no promesas)
    proj = []
    rates = dict(ASSUMPTIONS)
    if f["moneda"] == "USD":
        # Los depósitos en dólares en Perú suelen pagar menos que en soles: supuesto más prudente.
        for k in ("Depósitos con FSD y ahorro sin riesgo", "Depósitos con FSD"):
            rates[k] = 3.0
        alerts.append("Ahorras en dólares: los depósitos en dólares suelen pagar menos que en soles y tus gastos "
                      "son en soles, así que el tipo de cambio también mueve tu resultado. Compara ambas monedas "
                      "en el portal de la SBS.")
    blended = sum(pct / 100 * rates[name] for name, pct in alloc.items())
    infl = 3.0
    for years in (5, 10, 20):
        nominal = _fv(save, years, blended, 0)
        proj.append({"years": years, "contributed": round(save * 12 * years),
                     "nominal": round(nominal),
                     "today_money": round(nominal / (1 + infl / 100) ** years)})
    return {
        "disclaimer": ("Orientación educativa, no asesoría financiera personalizada. Antes de invertir fuera de "
                       "depósitos, consulta a un asesor autorizado por la SMV (Res. SMV 011-2026-SMV/01)."),
        "profile": prof, "steps": steps, "alerts": alerts,
        "projection": {"monthly": save, "currency": cur, "assumed_return_pct": round(blended, 2),
                       "assumed_inflation_pct": infl, "rows": proj,
                       "note": "Supuestos fijos para orientarte, no promesas. Para escenarios con caídas reales "
                               "usa 'goal' de TechMaC."},
        "red_flags": P.RED_FLAGS, "where_to_verify": P.WHERE_TO_VERIFY, "data_freshness": P.freshness(),
    }


def plan_markdown(plan):
    pr = plan["profile"]
    out = ["# Tu plan financiero", "", "> " + plan["disclaimer"], ""]
    if plan["data_freshness"]["warning"]:
        out += ["> **Atención:** " + plan["data_freshness"]["warning"], ""]
    out += ["## Tu perfil: %s" % pr["label"], "", pr["summary"], ""]
    for c in pr["caps_applied"]:
        out.append("- " + c)
    out += ["", "## Pasos, en este orden", ""]
    for i, s in enumerate(plan["steps"], 1):
        months = " (aprox. %d meses)" % s["months"] if s.get("months") else ""
        out += ["### %d. %s%s" % (i, s["step"], months), "", s["why"], ""]
        out += ["- " + h for h in s["how"]] + [""]
    pj = plan["projection"]
    out += ["## Proyección con %s %.0f al mes" % (pj["currency"], pj["monthly"]), "",
            "Supuesto: %.2f %% anual, inflación %.1f %%. %s" % (pj["assumed_return_pct"], pj["assumed_inflation_pct"], pj["note"]),
            "", "| Años | Aportado | Saldo estimado | En dinero de hoy |", "| --- | --- | --- | --- |"]
    for r in pj["rows"]:
        out.append("| %d | %s | %s | %s |" % (r["years"], format(r["contributed"], ","), format(r["nominal"], ","),
                                             format(r["today_money"], ",")))
    out += ["", "## Alertas", ""] + ["- " + a for a in plan["alerts"]]
    out += ["", "## Señales de estafa", ""] + ["- " + a for a in plan["red_flags"]]
    out += ["", "## Dónde verificar", ""] + ["- %s: %s" % (k, v) for k, v in plan["where_to_verify"].items()]
    out += ["", "Datos de Perú verificados el %s." % plan["data_freshness"]["verified"]]
    return "\n".join(out) + "\n"
