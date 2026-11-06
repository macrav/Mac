---
name: techmac
description: >-
  TechMaC, laboratorio local de backtesting serio y libro de órdenes en papel. Úsalo cuando el usuario
  pida probar, validar o comparar una estrategia de trading o inversión ("backtest", "¿funciona esta
  estrategia?", "evalúa SPY con cruce de medias", "walk-forward", "¿debería operar esto?"), descargar o
  importar datos de precios, proponer una orden, o revisar su libro, límites de riesgo o auditoría.
  Todo corre en local; TechMaC no se conecta a ningún broker y no puede ejecutar órdenes.
---

# TechMaC

Herramientas: el conector MCP `techmac` (data_status, list_strategies, backtest, evaluate,
list_evaluations, get_evaluation, propose_order, ledger_status, verify_audit) y la CLI
`python3 techmac/tm.py`. Usa el conector cuando esté disponible y la CLI cuando no.

## Flujo

1. **Datos.** `data_status`. Si faltan, que el usuario corra
   `python3 techmac/tm.py fetch SPY --interval 1d` (o `import-csv` con sus propios datos).
   El conector no tiene red a propósito.
2. **Explorar (opcional).** `backtest` es EN MUESTRA. Dilo siempre: sirve para entender la
   estrategia, no para decidir.
3. **Evaluar.** `evaluate` hace walk-forward fuera de muestra, costos x2, Monte Carlo por bloques,
   Deflated Sharpe y compara contra comprar y mantener. Es lo único que da un veredicto.
   Para portafolios globales usa `evaluate_portfolio` (con activo seguro, p. ej. SHY) y para comparar
   muchas estrategias a la vez `ranking`.
4. **Informar.** Da primero el veredicto y luego cada filtro que falló, con su valor. Si es RECHAZADA,
   dilo sin adornos y no propongas órdenes con esa estrategia. Si los datos son pocos (p. ej. 60 días
   de velas de 5 minutos), dilo: el resultado no es concluyente.
5. **Proponer.** Solo con una evaluación APROBADA del mismo símbolo: `propose_order`. Pasa por los
   límites de riesgo del usuario (config.json).
6. **Aprobar: nunca tú.** El usuario aprueba en SU terminal con
   `python3 techmac/tm.py approve <id>` y la frase exacta. Luego ejecuta la orden él mismo en su broker y
   registra el precio con `record-fill` y `record-exit`.

## Si el usuario quiere "hacerse rico rápido"

Usa `goal_simulator` y muéstrale la tabla: años hasta la meta, probabilidad de quiebra y de caer 50 %
según el apalancamiento. Explica sin sermonear que el apalancamiento acorta poco el plazo y dispara el
riesgo, y que lo que más mueve el resultado es el aporte mensual y el tiempo.

## Reglas

- APROBADA significa "candidata a prueba en papel", no "invierte". Recomienda varias semanas en papel
  y comparar `ledger_status` (expectativa real) con el backtest antes de arriesgar dinero.
- Nunca inventes resultados ni completes números que una herramienta no haya devuelto.
- Nunca intentes aprobar órdenes, desactivar el KILL, editar config.json para saltarte un límite ni
  tocar las bases de datos de `~/.techmac`.
- No es asesoría financiera. Menciónalo una vez cuando hables de invertir dinero real.
