"""Scrape discounted products from tailoy.com.pe.

Tai Loy runs Magento 2 and renders its product grids server-side, but it has no
offers collection and no discount filter: the "Top Ofertas" catalogue lives on
www1.tailoy.com.pe, which is not reachable from outside. So we walk the regular
categories and keep everything that carries a struck-out regular price.

Tai Loy exposes no low-stock signal anywhere in the listing markup, so these
rows never set `low_stock`.
"""
import re

from common import get, fanout

BASE = "https://www.tailoy.com.pe"

SOURCE = {
    "store": "Tai Loy",
    "domain": "tailoy.com.pe",
    "platform": "Magento 2",
    "how": "HTML renderizado en el servidor",
    "detail": ("Las 15 categorías del catálogo, conservando lo que lleva precio "
               "regular tachado. No publica stock, género ni tallas: su ficha sólo "
               "expone categoría, código y marca."),
    "gives": ["ofertas", "marca"],
}
CATEGORIES = [
    "escolar", "oficina", "jugueteria", "tecnologia", "lectura",
    "arte-y-dise-o", "manualidades", "hogar-y-decoracion", "electrohogar",
    "mundo-bebe", "mascotas", "abarrotes", "cuidado-personal-y-limpieza",
    "outdoors-deporte", "para-tu-emprendimiento",
]
PER_PAGE = 28
MAX_PAGES = 200  # guard against a pagination loop

ITEM = re.compile(r'<li class="item product product-item">(.*?)</li>', re.S)
LINK = re.compile(r'<a class="product-item-link"\s+href="([^"]+)">(.*?)</a>', re.S)
BRAND = re.compile(r'<div class="brand-label".*?<span class="label">(.*?)</span>', re.S)
FINAL = re.compile(r'data-price-amount="([\d.]+)"\s*\n?\s*data-price-type="finalPrice"')
OLD = re.compile(r'data-price-amount="([\d.]+)"\s*\n?\s*data-price-type="oldPrice"')
TOTAL = re.compile(r'de <span class="toolbar-number">(\d+)')


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def _parse(html):
    out = []
    for block in ITEM.findall(html):
        link = LINK.search(block)
        final = FINAL.search(block)
        if not link or not final:
            continue
        old = OLD.search(block)
        if not old:
            continue  # not discounted -> not an offer
        now, was = float(final.group(1)), float(old.group(1))
        if was <= now:
            continue
        brand = BRAND.search(block)
        out.append({
            "store": "Tai Loy",
            "id": link.group(1),
            "name": _clean(link.group(2)),
            "brand": _clean(brand.group(1)) if brand else "",
            "seller": "Tai Loy",
            "url": link.group(1),
            "price": f"S/ {now:,.2f}",
            "before": f"S/ {was:,.2f}",
            "discount": int(round((was - now) / was * 100)),
            "amount": now,
            "low_stock": None,  # Tai Loy publishes no stock signal
            "units": None,
            "gender": "",  # nor gender
            "sizes": [],   # nor sizes
        })
    return out


def _page_count(cat):
    html = get(f"{BASE}/{cat}.html")
    if not html:
        return 0, []
    m = TOTAL.search(html)
    total = int(m.group(1)) if m else len(_parse(html))
    pages = min(-(-total // PER_PAGE), MAX_PAGES) if total else 1
    return pages, _parse(html)


def scrape(log=print):
    items, seen = [], set()
    for cat in CATEGORIES:
        pages, first = _page_count(cat)
        if not pages:
            log(f"  tailoy {cat}: sin respuesta")
            continue
        found = list(first)
        if pages > 1:
            urls = [f"{BASE}/{cat}.html?p={p}" for p in range(2, pages + 1)]
            for html in fanout(lambda u: get(u), urls):
                found += _parse(html)
        new = 0
        for it in found:
            if it["url"] not in seen:
                seen.add(it["url"])
                items.append(it)
                new += 1
        # products sit in several categories at once, so `new` excludes repeats
        log(f"  tailoy {cat}: {pages} pags, {len(found)} con descuento, {new} nuevos")
    log(f"  tailoy: {len(items)} ofertas con descuento")
    return items
