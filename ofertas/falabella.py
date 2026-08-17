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
    }


def _check_stock(item):
    """Read the product page and record the fomo flag for this offer's own SKU."""
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

    items = fanout(_check_stock, items)
    low = sum(1 for i in items if i["low_stock"])
    log(f"  falabella: {len(items)} ofertas, {low} con pocas unidades")
    return items
