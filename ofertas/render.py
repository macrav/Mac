"""Render the collected offers into a single self-contained HTML page."""
import json
from datetime import datetime, timedelta, timezone

PERU = timezone(timedelta(hours=-5))

CSS = """
:root{
  --ground:#F7F8F6; --surface:#FFFFFF; --surface-2:#EFF2EE;
  --ink:#16201A; --ink-2:#4A574E; --ink-3:#77857B;
  --line:#DCE2DB; --line-2:#C8D1C6;
  --accent:#1F6F43; --accent-soft:#E3EFE7; --on-accent:#F7F8F6;
  --urgent:#96590C; --urgent-soft:#FBEFDD; --on-urgent:#FFFFFF;
  --deal:#B21E35; --deal-soft:#FAE6E9;
  --focus:#1F6F43;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#0F1411; --surface:#171E19; --surface-2:#1F2822;
    --ink:#E8EDE7; --ink-2:#A7B4AB; --ink-3:#7D8B83;
    --line:#2A342D; --line-2:#3A463D;
    --accent:#6BC08C; --accent-soft:#1B2E22; --on-accent:#0F1411;
    --urgent:#E5A542; --urgent-soft:#33240E; --on-urgent:#12160F;
    --deal:#F0879B; --deal-soft:#33141B;
    --focus:#6BC08C;
  }
}
:root[data-theme="dark"]{
  --ground:#0F1411; --surface:#171E19; --surface-2:#1F2822;
  --ink:#E8EDE7; --ink-2:#A7B4AB; --ink-3:#7D8B83;
  --line:#2A342D; --line-2:#3A463D;
  --accent:#6BC08C; --accent-soft:#1B2E22; --on-accent:#0F1411;
  --urgent:#E5A542; --urgent-soft:#33240E; --on-urgent:#12160F;
  --deal:#F0879B; --deal-soft:#33141B;
  --focus:#6BC08C;
}
*{box-sizing:border-box}
body{margin:0; background:var(--ground); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:16px; line-height:1.55; -webkit-font-smoothing:antialiased}
.wrap{max-width:1080px; margin:0 auto; padding:40px 20px 80px;
  display:flex; flex-direction:column; gap:30px}

header{display:flex; flex-direction:column; gap:10px}
.eyebrow{font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent); font-weight:650}
h1{font-family:Georgia,"Iowan Old Style","Times New Roman",serif;
  font-weight:600; font-size:clamp(30px,5vw,44px); line-height:1.12;
  margin:0; text-wrap:balance; letter-spacing:-.01em}
.sub{color:var(--ink-2); max-width:65ch; margin:0; font-size:15.5px}

.stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px}
.stat{background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; display:flex; flex-direction:column; gap:3px}
.stat .k{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:29px; font-weight:600; font-variant-numeric:tabular-nums; line-height:1}
.stat .t{font-size:12px; letter-spacing:.07em; text-transform:uppercase;
  color:var(--ink-3); font-weight:600}
.stat.u .k{color:var(--urgent)} .stat.d .k{color:var(--deal)} .stat.a .k{color:var(--accent)}

.controls{display:flex; flex-direction:column; gap:10px;
  position:sticky; top:0; z-index:5; background:var(--ground);
  padding:12px 0; border-bottom:1px solid var(--line)}
.bar{display:flex; flex-wrap:wrap; gap:10px; align-items:center}
.legend{font-size:11.5px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--ink-3); font-weight:650; margin-right:2px}
.chips{display:flex; flex-wrap:wrap; gap:7px}
.chip{font:inherit; font-size:13.5px; font-weight:550; cursor:pointer;
  background:var(--surface); color:var(--ink-2);
  border:1px solid var(--line-2); border-radius:999px; padding:6px 14px;
  transition:background .13s, color .13s, border-color .13s}
.chip:hover{border-color:var(--accent); color:var(--ink)}
.chip[aria-pressed="true"]{background:var(--accent); border-color:var(--accent);
  color:var(--on-accent)}
.spacer{flex:1 1 auto}
input[type=search],select{font:inherit; font-size:14px; color:var(--ink);
  background:var(--surface); border:1px solid var(--line-2); border-radius:8px;
  padding:7px 11px}
input[type=search]{min-width:190px}
:focus-visible{outline:2px solid var(--focus); outline-offset:2px}
.count{font-size:13px; color:var(--ink-3); font-variant-numeric:tabular-nums}

.list{display:flex; flex-direction:column; border:1px solid var(--line);
  border-radius:12px; overflow:hidden; background:var(--surface)}
.row{display:grid; grid-template-columns:1fr auto; gap:6px 20px;
  padding:16px 18px; border-top:1px solid var(--line); align-items:center}
.row:first-child{border-top:none}
.row:nth-child(even){background:var(--surface-2)}
.main{display:flex; flex-direction:column; gap:6px; min-width:0}
.name{font-weight:600; font-size:15.5px; line-height:1.35; margin:0}
.name a{color:var(--ink); text-decoration:none; text-underline-offset:3px}
.name a:hover{text-decoration:underline; color:var(--accent)}
.meta{font-size:12.5px; color:var(--ink-3); display:flex; flex-wrap:wrap; gap:4px 10px}
.store{font-weight:650; color:var(--ink-2)}
.tags{display:flex; flex-wrap:wrap; gap:6px}
.tag{font-size:11.5px; font-weight:650; letter-spacing:.03em;
  padding:2.5px 8px; border-radius:5px; white-space:nowrap}
.tag.low{background:var(--urgent); color:var(--on-urgent); border:1px solid var(--urgent)}
.tag.off{background:var(--deal-soft); color:var(--deal);
  border:1px solid color-mix(in srgb, var(--deal) 30%, transparent)}

.price{display:flex; flex-direction:column; align-items:flex-end; gap:1px;
  font-variant-numeric:tabular-nums; white-space:nowrap}
.now{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:18px; font-weight:600; letter-spacing:-.02em}
.was{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12.5px; color:var(--ink-3); text-decoration:line-through}
.empty{padding:44px 18px; text-align:center; color:var(--ink-3); font-size:14.5px}
.more{margin:0 auto; display:block}

footer{color:var(--ink-3); font-size:13px; border-top:1px solid var(--line);
  padding-top:20px; display:flex; flex-direction:column; gap:8px}
footer p{margin:0; max-width:70ch}
footer a{color:var(--accent)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em;
  background:var(--surface-2); padding:1px 5px; border-radius:4px}

@media (max-width:620px){
  .row{grid-template-columns:1fr}
  .price{flex-direction:row; gap:10px; align-items:baseline}
  .controls{position:static}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = r"""
const DATA = __DATA__;
const PAGE = 200;
let shown = PAGE, kind = 'low', store = 'all';
const list = document.getElementById('list');
const count = document.getElementById('count');
const q = document.getElementById('q');
const sortSel = document.getElementById('sort');
const more = document.getElementById('more');
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function current(){
  const term = q.value.trim().toLowerCase();
  let r = DATA.filter(x => {
    if (store !== 'all' && x.t !== store) return false;
    if (kind === 'low' && !x.l) return false;
    if (kind === 'deal' && !x.d) return false;
    if (kind === 'both' && !(x.l && x.d)) return false;
    if (term && !(x.n + ' ' + x.b + ' ' + x.s).toLowerCase().includes(term)) return false;
    return true;
  });
  const s = sortSel.value;
  if (s === 'price-asc') r.sort((a,b) => a.v - b.v);
  else if (s === 'price-desc') r.sort((a,b) => b.v - a.v);
  else if (s === 'disc') r.sort((a,b) => b.d - a.d || a.v - b.v);
  else r.sort((a,b) => (b.l - a.l) || (a.k - b.k) || (b.d - a.d));
  return r;
}

function render(){
  const r = current();
  count.textContent = r.length + (r.length === 1 ? ' producto' : ' productos');
  if (!r.length){
    list.innerHTML = '<p class="empty">Ningún producto coincide con ese filtro o búsqueda.</p>';
    more.hidden = true;
    return;
  }
  list.innerHTML = r.slice(0, shown).map(x => {
    const tags = [];
    if (x.l) tags.push('<span class="tag low">Pocas unidades' +
      (x.k ? ' · quedan ' + x.k : '') + '</span>');
    if (x.d) tags.push('<span class="tag off">-' + x.d + '%</span>');
    const meta = ['<span class="store">' + esc(x.t) + '</span>']
      .concat([x.b, x.s].filter(Boolean).map(t => '<span>' + esc(t) + '</span>')).join('');
    return '<div class="row"><div class="main">' +
      '<p class="name"><a href="' + esc(x.u) + '" target="_blank" rel="noopener noreferrer">' +
        esc(x.n) + '</a></p>' +
      '<div class="meta">' + meta + '</div>' +
      (tags.length ? '<div class="tags">' + tags.join('') + '</div>' : '') +
      '</div><div class="price"><span class="now">' + esc(x.p) + '</span>' +
      (x.w ? '<span class="was">' + esc(x.w) + '</span>' : '') + '</div></div>';
  }).join('');
  more.hidden = r.length <= shown;
  more.textContent = 'Ver ' + Math.min(PAGE, r.length - shown) + ' más';
}

function group(sel, set){
  document.querySelectorAll(sel).forEach(c => c.addEventListener('click', () => {
    document.querySelectorAll(sel).forEach(o =>
      o.setAttribute('aria-pressed', String(o === c)));
    set(c.dataset.v); shown = PAGE; render();
  }));
}
group('.chip[data-g="kind"]', v => kind = v);
group('.chip[data-g="store"]', v => store = v);
q.addEventListener('input', () => { shown = PAGE; render(); });
sortSel.addEventListener('change', () => { shown = PAGE; render(); });
more.addEventListener('click', () => { shown += PAGE; render(); });
render();
"""


def build(items, path="ofertas.html"):
    rows = []
    for x in items:
        rows.append({
            "t": x["store"], "n": x["name"], "b": x.get("brand") or "",
            "s": x.get("seller") or "", "u": x["url"], "p": x["price"],
            "w": x.get("before") or "", "d": int(x.get("discount") or 0),
            "l": 1 if x.get("low_stock") else 0, "k": x.get("units") or 0,
            "v": float(x.get("amount") or 0),
        })
    rows.sort(key=lambda r: (-r["l"], -r["d"], r["v"]))

    total = len(rows)
    low = sum(r["l"] for r in rows)
    deal = sum(1 for r in rows if r["d"])
    both = sum(1 for r in rows if r["l"] and r["d"])
    stores = sorted({r["t"] for r in rows})
    stamp = datetime.now(PERU).strftime("%d/%m/%Y a las %H:%M")

    store_chips = "".join(
        f'<button class="chip" data-g="store" data-v="{s}" aria-pressed="false">{s}</button>'
        for s in stores)

    html = f"""<title>Radar de Ofertas Perú</title>
<style>{CSS}</style>
<div class="wrap">
<header>
  <span class="eyebrow">Falabella &middot; Tai Loy &nbsp;|&nbsp; {stamp}</span>
  <h1>Ofertas con pocas unidades disponibles</h1>
  <p class="sub">Ofertas vigentes en las tiendas peruanas que publican su catálogo
  de forma consultable. Falabella además expone un indicador de stock bajo, que se
  lee producto por producto. Cada fila enlaza directo a la ficha.</p>
</header>

<section class="stats" aria-label="Resumen">
  <div class="stat"><span class="k">{total}</span><span class="t">Ofertas</span></div>
  <div class="stat u"><span class="k">{low}</span><span class="t">Pocas unidades</span></div>
  <div class="stat d"><span class="k">{deal}</span><span class="t">Con descuento</span></div>
  <div class="stat a"><span class="k">{both}</span><span class="t">Ambos</span></div>
</section>

<div class="controls">
  <div class="bar">
    <span class="legend">Mostrar</span>
    <div class="chips" role="group" aria-label="Filtrar por tipo">
      <button class="chip" data-g="kind" data-v="low" aria-pressed="true">Pocas unidades</button>
      <button class="chip" data-g="kind" data-v="deal" aria-pressed="false">Con descuento</button>
      <button class="chip" data-g="kind" data-v="both" aria-pressed="false">Ambos</button>
      <button class="chip" data-g="kind" data-v="all" aria-pressed="false">Todo</button>
    </div>
  </div>
  <div class="bar">
    <span class="legend">Tienda</span>
    <div class="chips" role="group" aria-label="Filtrar por tienda">
      <button class="chip" data-g="store" data-v="all" aria-pressed="true">Todas</button>
      {store_chips}
    </div>
    <span class="spacer"></span>
    <input type="search" id="q" placeholder="Buscar producto o marca" aria-label="Buscar">
    <select id="sort" aria-label="Ordenar">
      <option value="rel">Más urgente primero</option>
      <option value="disc">Mayor descuento</option>
      <option value="price-asc">Precio: menor a mayor</option>
      <option value="price-desc">Precio: mayor a menor</option>
    </select>
  </div>
</div>

<p class="count" id="count"></p>
<main class="list" id="list"></main>
<button class="chip more" id="more" hidden>Ver más</button>

<footer>
  <p><strong>Cómo se arma.</strong> De Falabella se recorre la colección
  <em>Ofertas</em> y se abre la ficha de cada producto para leer su indicador interno
  de stock bajo (<code>fomo</code>), el mismo que alimenta el aviso “Pocas unidades
  disponibles”. De Tai Loy se recorren todas las categorías y se conserva lo que lleva
  precio regular tachado.</p>
  <p><strong>Límites.</strong> Falabella hoy no dibuja ese aviso en su web de escritorio
  (trae el interruptor <code>isFomoBadgeVisible</code> apagado), así que el dato sale de la
  ficha y no de la pantalla; su contador sólo devuelve 1 o 4, o sea marca urgencia y no
  inventario exacto. Tai Loy no publica ninguna señal de stock, por eso sus filas nunca
  llevan la etiqueta ámbar. Ripley y adidas.pe quedan fuera: bloquean el acceso
  automatizado con Cloudflare y Akamai. Precios y stock cambian durante el día.</p>
</footer>
</div>
<script>{JS.replace('__DATA__', json.dumps(rows, ensure_ascii=False))}</script>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return {"path": path, "total": total, "low": low, "deal": deal,
            "both": both, "stores": stores, "stamp": stamp}
