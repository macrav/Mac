"""Datos de Perú que usa el asesor. Verificados el 2026-11-07; cada uno trae su fuente.

Las cifras cambian (el FSD se ajusta cada trimestre, las tasas cada mes, las leyes cuando el Congreso
las aprueba). El asesor avisa cuando estos datos tienen más de 90 días.
"""

import datetime as dt

VERIFIED = dt.date(2026, 11, 7)
STALE_AFTER_DAYS = 90

FACTS = {
    "fsd_limit_pen": {
        "value": 123000, "period": "septiembre a noviembre de 2026",
        "text": "El Fondo de Seguro de Depósitos cubre hasta S/ 123,000 por persona y por entidad (bancos, "
                "financieras y cajas). Los depósitos en dólares se pagan en su equivalente en soles. Las "
                "cooperativas tienen otro fondo (FSDC) con un límite mucho menor. Se actualiza cada trimestre.",
        "source": "https://elperuano.pe/noticia/304049-tus-ahorros-tienen-una-nueva-cobertura-el-fondo-de-seguro-de-depositos-fija-el-limite-en-s123000",
    },
    "uit_pen": {
        "value": 5500, "period": "2026",
        "text": "La UIT 2026 es S/ 5,500 (D.S. 301-2025-EF).",
        "source": "https://lpderecho.pe/valor-uit-2026-decreto-supremo-301-2025-ef/",
    },
    "bcrp_rate_pct": {
        "value": 4.25, "period": "octubre de 2026 (próxima decisión: 12 de noviembre)",
        "text": "Tasa de referencia del BCRP: 4.25 %, sin cambios desde septiembre de 2025.",
        "source": "https://larepublica.pe/amp/economia/2026/10/07/bcrp-mantiene-tasa-de-referencia-en-425-por-mas-de-un-ano-pese-a-inflacion-de-45-hnews-237097",
    },
    "inflation_pct": {
        "value": 4.5, "period": "septiembre de 2026, anual",
        "text": "Inflación anual 4.5 % a septiembre de 2026, sobre el rango meta del BCRP (1 % a 3 %). Un "
                "ahorro que rinde menos que la inflación pierde poder de compra aunque no baje de saldo.",
        "source": "https://larepublica.pe/amp/economia/2026/10/07/bcrp-mantiene-tasa-de-referencia-en-425-por-mas-de-un-ano-pese-a-inflacion-de-45-hnews-237097",
    },
    "deposit_rates": {
        "value": {"bancos_grandes_pct": [2.9, 3.8], "cajas_financieras_max_pct": [5.9, 7.1]},
        "period": "datos SBS a marzo de 2026 (depósitos a más de 360 días en soles)",
        "text": "Depósitos a plazo en soles: los bancos grandes pagan aprox. 2.9 % a 3.8 % anual y las cajas y "
                "financieras mejor pagadas, aprox. 5.9 % a 7.1 %. Compara la TREA vigente en el portal de la SBS "
                "antes de elegir; las tasas cambian cada mes.",
        "source": "https://www.expreso.com.pe/economia/depositos-a-plazo-fijo-2026-descubre-que-banco-o-caja-paga-el-mayor-interes-por-tus-ahorros-caja-cusco-fondo-de-seguro-de-depositos-caja-incasur-noticia/1305024/",
    },
    "deposit_interest_tax": {
        "value": "exonerado hasta 2026-12-31",
        "period": "noviembre de 2026",
        "text": "Los intereses de depósitos de personas naturales están exonerados del impuesto a la renta hasta "
                "el 31 de diciembre de 2026 (art. 19 LIR). La Comisión de Economía aprobó extenderlo hasta 2029 "
                "(31 de octubre de 2026), pero falta el voto del Pleno y su publicación. Si no se prorroga, "
                "tributarían 5 %.",
        "source": "https://www.infobae.com/peru/2026/10/31/cuentas-de-ahorro-no-pagarian-impuesto-a-la-renta-en-2027-comision-de-economia-aprobo-dictamen/",
    },
    "mutual_funds": {
        "value": {"deuda_soles_12m_pct": [3.5, 3.8]},
        "period": "agosto de 2026",
        "text": "Fondos mutuos de deuda en soles: aprox. 3.5 % a 3.8 % en 12 meses. Se compran desde S/ 20 o "
                "US$ 5 en administradoras autorizadas por la SMV. NO tienen seguro de depósitos: pueden bajar, "
                "aunque los de corto plazo rara vez y poco.",
        "source": "https://www.infobae.com/peru/2026/09/17/fondos-mutuos-baten-record-en-peru-con-s64769-millones-administrados-estas-fueron-las-carteras-mas-rentables/",
    },
    "afp_voluntary": {
        "value": {"fondo0_12m_pct": 4.4, "fondo1_12m_pct": 7.5, "fondo2_12m_pct": 17, "fondo3_12m_pct": 31},
        "period": "12 meses a septiembre de 2026",
        "text": "Aportes voluntarios SIN fin previsional en una AFP: eliges Fondo 0, 1, 2 o 3 y puedes retirar. "
                "Desde 2026, la rentabilidad al retirar está inafecta al impuesto a la renta (Ley 32123). El Fondo 0 "
                "es el de menor riesgo. Los retornos de un año no se repiten necesariamente.",
        "source": "https://gestion.pe/tu-dinero/finanzas-personales/inversiones-en-fondos-de-afp-de-libre-retiro-crecieron-en-49-el-ultimo-ano-fue-rentable-noticia/",
    },
    "capital_gains_tax": {
        "value": {"fuente_peruana_pct": 5, "fuente_extranjera_pct": [8, 30]},
        "period": "2026",
        "text": "Ganancias por venta de valores de fuente peruana: 5 % efectivo (6.25 % sobre el 80 %). Valores "
                "emitidos en el extranjero (p. ej. un ETF de EE. UU. comprado con un broker internacional): renta "
                "de fuente extranjera, que se suma a tus rentas de trabajo con la escala de 8 % a 30 %, salvo "
                "excepciones del art. 51 de la LIR. Consulta con un contador antes de invertir fuera.",
        "source": "https://www.rankia.pe/blog/analisis-igbvl/6512611-impuestos-inversiones-peru",
    },
    "us_estate_tax": {
        "value": {"exemption_usd": 60000, "max_rate_pct": 40},
        "period": "vigente",
        "text": "Si un no residente de EE. UU. fallece con más de US$ 60,000 en activos de EE. UU. (incluidas "
                "acciones y ETFs domiciliados allí), sus herederos pueden pagar hasta 40 % de impuesto de "
                "sucesiones. Los ETFs UCITS domiciliados en Irlanda suelen evitarlo. Verifícalo con un asesor "
                "tributario internacional.",
        "source": "https://www.jmco.com/articles/international-tax/nonresident-alien-tax-trap/",
    },
    "smv_regulation": {
        "value": "Res. SMV 011-2026-SMV/01",
        "period": "vigente desde el 18 de agosto de 2026",
        "text": "La SMV regula la asesoría de inversión y el perfilamiento del cliente como servicios con "
                "obligaciones propias (contrato previo; adecuación hasta el 31 de marzo de 2027). Solo las "
                "sociedades agentes de bolsa (SAB) pueden intermediar valores. Las 'gestoras de fondos privados' "
                "no están supervisadas por la SMV.",
        "source": "https://lpderecho.pe/smv-modifica-reglamentos-de-agentes-de-intermediacion-de-fondos-mutuos-de-inversion-en-valores-y-de-fondos-de-inversion-res-smv-011-2026-smv-01/",
    },
    "consumer_credit": {
        "value": {"tea_consumo_promedio_pct": 58, "tope_soles_pct": 114.13},
        "period": "2026 (tope mayo a octubre)",
        "text": "El crédito de consumo cuesta en promedio cerca de 58 % TEA en Perú y el tope legal en soles fue "
                "114.13 % (mayo a octubre de 2026). Ninguna inversión legítima rinde eso de forma segura: pagar "
                "deudas caras es la mejor 'inversión' sin riesgo.",
        "source": "https://andina.pe/agencia/noticia-tasas-interes-tarjetas-credito-consumo-fluctuan-entre-23-y-153-755070.aspx",
    },
    "independent_workers_pension": {
        "value": "voluntario",
        "period": "2026",
        "text": "El aporte previsional de los trabajadores independientes sigue siendo voluntario (D.S. "
                "061-2026-EF). Si no aportas, tu jubilación depende 100 % de tu propio ahorro.",
        "source": "https://www.infobae.com/peru/2026/04/16/gobierno-elimina-la-obligacion-de-aportes-previsionales-para-trabajadores-independientes-a-partir-de-2028/",
    },
}

RED_FLAGS = [
    "Te prometen una rentabilidad fija o 'garantizada' alta (más de lo que paga un depósito).",
    "La entidad no aparece en el registro de la SMV (gob.pe/smv) ni en el de la SBS.",
    "Te piden pagar por WhatsApp, Telegram, cripto o a una cuenta personal.",
    "Te presionan para decidir hoy o te ofrecen bonos por traer a otras personas (esquema Ponzi o pirámide).",
    "Forex, CFD o 'copy trading' ofrecidos al público sin autorización de la SMV.",
    "Alguien dice hablar en nombre de la SMV y pide dinero: la SMV nunca pide dinero a inversionistas.",
]

WHERE_TO_VERIFY = {
    "SMV (SAB, fondos mutuos, alertas)": "https://www.gob.pe/smv",
    "SBS (bancos, cajas, AFP, tasas)": "https://www.sbs.gob.pe",
    "BCRP (tasa de referencia, inflación)": "https://www.bcrp.gob.pe",
    "SUNAT (impuestos)": "https://www.sunat.gob.pe",
}


def freshness(today=None):
    today = today or dt.date.today()
    age = (today - VERIFIED).days
    return {"verified": str(VERIFIED), "age_days": age, "stale": age > STALE_AFTER_DAYS,
            "warning": ("Los datos de Perú tienen %d días. Pide a Claude que los vuelva a verificar antes de "
                        "decidir." % age) if age > STALE_AFTER_DAYS else None}
