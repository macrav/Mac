"""Scrape the falabella.com.pe "Ofertas" collection.

Falabella ships the listing as JSON inside the page's __NEXT_DATA__ blob. The
"Pocas unidades disponibles" notice is driven by a per-variant `fomo` field that
only appears on the product page, so every offer is opened once to read it.
"""
import json
import re

from common import get, fanout

COLLECTION = "https://www.falabella.com.pe/falabella-pe/collection/ofertas"
PAGES = 6  # the collection runs to ~5 pages; the extra one is slack
NEXT = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

SOURCE = {
    "store": "Falabella",
    "domain": "falabella.com.pe",
    "platform": "Next.js",
    "how": "JSON incrustado en <code>__NEXT_DATA__</code>",
    "detail": ("Colección <em>Ofertas</em> paginada, más la ficha de cada producto "
               "para leer el stock bajo (<code>fomo</code>), el género y las tallas."),
    "gives": ["ofertas", "pocas unidades", "género", "tallas", "marca"],
}


def _listing(url):
    m = NEXT.search(get(url))
    if not m:
        return []
    try:
        return json.loads(m.group(1))["props"]["pageProps"].get("results") or []
    except (ValueError, KeyError):
        return []


def _prices(p):
    """Return (current, crossed-out) as display strings."""
    current = crossed = ""
    for pr in p.get("prices") or []:
        vals = pr.get("price") or []
        if not vals:
            continue
        sym = pr.get("symbol", "")
        txt = sym + (vals[0] if len(vals) == 1 else f"{vals[0]} - {sym}{vals[-1]}")
        if pr.get("type") == "normalPrice" and pr.get("crossed"):
            crossed = txt
        elif pr.get("type") in ("eventPrice", "internetPrice") and not current:
            current = txt
    return current, crossed


def _amount(text):
    m = re.search(r"([\d.,]+)", text or "")
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return 0.0


def _sizes(p):
    """Sizes offered for this product, preferring the ones still purchasable."""
    live, all_of = [], []
    for v in p.get("variants") or []:
        for o in v.get("options") or []:
            for s in o.get("sizes") or []:
                label = (s.get("value") or "").strip()
                if not label:
                    continue
                all_of.append(label)
                if s.get("available"):
                    live.append(label)
    picked = live or all_of
    return sorted({s for s in picked}, key=picked.index)


def _flat(p):
    current, crossed = _prices(p)
    badge = (p.get("discountBadge") or {}).get("label") or ""
    return {
        "store": "Falabella",
        "id": p.get("productId"),
        "sku": p.get("skuId"),
        "name": p.get("displayName"),
        "brand": p.get("brand") or "",
        "seller": p.get("sellerName") or "",
        "url": p.get("url"),
        "price": current,
        "before": crossed,
        "discount": int(re.sub(r"\D", "", badge) or 0),
        "amount": _amount(current),
        "low_stock": None,
        "units": None,
        "gender": "",
        "sizes": _sizes(p),
    }


def _gender(pd):
    """Falabella files gender as a product specification, not a listing field."""
    for spec in (pd.get("attributes") or {}).get("specifications") or []:
        name = (spec.get("name") or "").strip().lower()
        sid = spec.get("id") or ""
        if name in ("género", "genero") or "genero" in sid:
            value = (spec.get("value") or "").strip()
            if value:
                return value[0].upper() + value[1:]
    return ""


def _enrich(item):
    """Open the product page for the fomo flag, the gender and any missing sizes."""
    m = NEXT.search(get(item["url"], tries=2, minlen=20000))
    if not m:
        return item
    try:
        pd = json.loads(m.group(1))["props"]["pageProps"]["productData"]
    except (ValueError, KeyError):
        return item

    variants = {str(v.get("id")): v for v in pd.get("variants") or []}
    v = variants.get(str(item["sku"])) or variants.get(str(pd.get("currentVariant")))
    if v:
        fomo = v.get("fomo") or {}
        item["low_stock"] = bool(fomo.get("enabled"))
        item["units"] = fomo.get("remainingUnits")

    item["gender"] = _gender(pd)
    if not item["sizes"]:
        found = []
        for var in pd.get("variants") or []:
            for s in var.get("sizes") or []:
                label = (s.get("value") or s.get("label") or "").strip()
                if label and label not in found:
                    found.append(label)
        item["sizes"] = found
    return item


def scrape(log=print):
    items, seen = [], set()
    for n in range(1, PAGES + 1):
        rows = _listing(COLLECTION if n == 1 else f"{COLLECTION}?page={n}")
        if not rows:
            break
        for p in rows:
            f = _flat(p)
            if f["id"] and f["id"] not in seen:
                seen.add(f["id"])
                items.append(f)
        log(f"  falabella pagina {n}: {len(rows)} resultados ({len(items)} unicos)")

    items = fanout(_enrich, items)
    low = sum(1 for i in items if i["low_stock"])
    gen = sum(1 for i in items if i["gender"])
    siz = sum(1 for i in items if i["sizes"])
    log(f"  falabella: {len(items)} ofertas, {low} con pocas unidades, "
        f"{gen} con género, {siz} con tallas")
    return items
