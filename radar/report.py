"""prices.csv'den günlük özet (Telegram) ve panel (docs/index.html) üretir."""
from __future__ import annotations

import csv
import html
import json
import os
from collections import defaultdict
from pathlib import Path

import requests

from .scrape import PRICES, ROOT, load_config

DOCS = ROOT / "docs" / "index.html"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_history() -> dict:
    """{(product_key, site): [(date, unit_price, row), ...]} tarihe göre sıralı"""
    hist = defaultdict(list)
    if not PRICES.exists():
        return hist
    with PRICES.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            hist[(r["product_key"], r["site"])].append((r["date"], _f(r["unit_price"]), r))
    for v in hist.values():
        v.sort(key=lambda t: t[0])
    return hist


def summarize() -> dict:
    cfg = load_config()
    hist = load_history()
    dates = sorted({d for v in hist.values() for d, _, _ in v})
    today = dates[-1] if dates else None
    out = {"date": today, "products": [], "alerts": [], "free_shipping": cfg.get("free_shipping", {})}

    for prod in cfg["products"]:
        sites = []
        for off in prod["offers"]:
            series = hist.get((prod["key"], off["site"]), [])
            valid = [(d, p) for d, p, _ in series if p]
            cur = next((p for d, p, _ in series if d == today and p), None)
            last_row = series[-1][2] if series else {}
            prev = next((p for d, p in reversed(valid) if d < today), None) if today else None
            change = (cur - prev) / prev * 100 if cur and prev else None
            sites.append({"site": off["site"], "own": bool(off.get("own")), "url": off["url"],
                          "price": cur, "prev": prev, "change": change,
                          "in_stock": last_row.get("in_stock", ""), "status": last_row.get("status", "veri yok"),
                          "series": valid[-30:]})
        own = [s["price"] for s in sites if s["own"] and s["price"]]
        comp = [s for s in sites if not s["own"] and s["price"] and str(s["in_stock"]) != "False"]  # tükenenler sayılmaz
        our = min(own) if own else None
        our_url = next((st["url"] for st in sites if st["own"] and st["price"] == our), None)
        cheapest = min(comp, key=lambda s: s["price"]) if comp else None
        avg = sum(s["price"] for s in comp) / len(comp) if comp else None
        rank = 1 + sum(1 for s in comp if our and s["price"] < our) if our else None
        show = prod.get("show") or {"qty": 1, "label": "1 " + prod["unit"]}
        out["products"].append({"key": prod["key"], "name": prod["name"], "unit": prod["unit"], "show": show,
                                "our": our, "cheapest": cheapest and {"site": cheapest["site"], "price": cheapest["price"], "url": cheapest["url"]},
                                "our_url": our_url,
                                "avg": avg, "rank": rank, "n": len(comp) + (1 if our else 0), "sites": sites})
        for s in sites:
            if s["change"] is not None and abs(s["change"]) >= 3:
                out["alerts"].append(f"{prod['name']}: {s['site']} {'▲' if s['change'] > 0 else '▼'} %{abs(s['change']):.0f} "
                                     f"({s['prev']:.0f} → {s['price']:.0f} ₺/{prod['unit']})")
        if our and cheapest and cheapest["price"] < our * 0.95:
            out["alerts"].append(f"{prod['name']}: {cheapest['site']} bizden %{(1 - cheapest['price'] / our) * 100:.0f} ucuz "
                                 f"({cheapest['price']:.0f} vs {our:.0f} ₺/{prod['unit']})")
    return out


_AYLAR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _tl(x: float) -> str:
    return f"{x:,.0f} ₺".replace(",", ".")


def _a(text: str, url: str | None) -> str:
    t = html.escape(text, quote=False)
    return f'<a href="{html.escape(url, quote=True)}">{t}</a>' if url else t


def telegram_text(s: dict, panel_url: str = "") -> str:
    y, m, d = (s["date"] or "0000-00-00").split("-")
    lines = [f"🍈 <b>Tropik Fiyat Radarı — {int(d)} {_AYLAR[int(m)]}</b>", ""]
    pahali, ucuz, degisen = [], [], []
    for p in s["products"]:
        q, lbl = p["show"]["qty"], p["show"]["label"]
        title = html.escape(p["name"], quote=False)
        biz_l = _a("Biz", p.get("our_url"))
        rk = p["cheapest"] and _a(p["cheapest"]["site"], p["cheapest"]["url"])
        if p["our"] and p["cheapest"]:
            biz, rakip = p["our"] * q, p["cheapest"]["price"] * q
            if rakip < biz:
                pahali.append(f"▪️ <b>{title}</b>\n   {biz_l}: {_tl(biz)} · {rk}: {_tl(rakip)}  ({_tl(biz - rakip)} ucuz)")
            else:
                fark = f"{_tl(rakip - biz)} pahalı" if rakip > biz else "aynı fiyat"
                ucuz.append(f"<b>{title}</b>\n   {biz_l}: {_tl(biz)} · En yakın: {rk} {_tl(rakip)}  ({fark})")
        for st in p["sites"]:
            if st["change"] is not None and abs(st["change"]) >= 3:
                yon = "zam 📈" if st["change"] > 0 else "indirim 📉"
                kim = _a("Biz" if st["own"] else st["site"], st["url"])
                degisen.append(f"▪️ {kim} — {title}: {_tl(st['prev'] * q)} → {_tl(st['price'] * q)} ({yon})")
    if pahali:
        lines.append(f"🔴 <b>Rakip bizden UCUZ ({len(pahali)} ürün):</b>")
        lines += pahali + [""]
    if ucuz:
        lines.append(f"🟢 <b>En ucuz BİZİZ ({len(ucuz)} ürün):</b>")
        lines += [f"▪️ {n}" for n in ucuz]
        lines.append("")
    lines.append("🔄 <b>Dünden bugüne fiyat değişimi:</b>")
    lines += degisen or ["Değişiklik yok."]
    lines.append("\n<i>'Biz' ya da rakip adına tıklayınca ürün sayfası açılır.</i>\nNot: 'Biz' = iki sitemizden (Tropik Hasat / Bizim Tropikal) ucuz olanı. Stokta olmayan rakipler sayılmaz.")
    if panel_url:
        lines.append(_a("Detaylı tablo", panel_url))
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram ayarı yok, mesaj gönderilmedi.\n" + text)
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20)
    if not r.ok:
        print("Telegram hatası:", r.status_code, r.text[:200])
    r.raise_for_status()


def _spark(series) -> str:
    pts = [p for _, p in series]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    w, h = 90, 24
    xy = " ".join(f"{i * w / (len(pts) - 1):.1f},{h - 2 - (p - lo) / rng * (h - 4):.1f}" for i, p in enumerate(pts))
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{xy}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>'


def render_html(s: dict) -> str:
    e = html.escape
    cards = []
    for p in s["products"]:
        rows = []
        for st in sorted(p["sites"], key=lambda x: (x["price"] is None, x["price"] or 0)):
            if st["price"]:
                ch = st["change"]
                arrow = "" if ch is None or abs(ch) < 0.5 else (f'<span class="up">▲ %{ch:.0f}</span>' if ch > 0 else f'<span class="down">▼ %{abs(ch):.0f}</span>')
                price = f"{st['price']:,.0f} ₺".replace(",", ".")
            else:
                arrow, price = "", f'<span class="muted">{e(st["status"])}</span>'
            stock = ' <span class="muted">(tükendi)</span>' if str(st["in_stock"]) == "False" else ""
            rows.append(f'<tr class="{"own" if st["own"] else ""}"><td><a href="{e(st["url"])}" target="_blank" rel="noopener">{e(st["site"])}</a>{stock}</td>'
                        f'<td class="num">{price}</td><td class="num">{arrow}</td><td>{_spark(st["series"])}</td></tr>')
        badge = ""
        if p["rank"]:
            badge = f'<span class="badge {"good" if p["rank"] == 1 else "bad" if p["rank"] == p["n"] else ""}">{p["rank"]}. / {p["n"]}</span>'
        cards.append(f'<section class="card"><h2>{e(p["name"])} {badge}</h2><p class="muted">₺ / {e(p["unit"])} — sıra: 1 = en ucuz</p>'
                     f'<table>{"".join(rows)}</table></section>')
    alerts = "".join(f"<li>{e(a)}</li>" for a in s["alerts"]) or "<li>Kayda değer değişiklik yok.</li>"
    ship = ", ".join(f"{e(k)}: {v:,} ₺".replace(",", ".") if v else f"{e(k)}: ?" for k, v in s["free_shipping"].items())
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tropik Fiyat Radarı</title><style>
:root{{--bg:#f7f6f2;--card:#fff;--ink:#1d2b22;--muted:#6b7a70;--green:#1f7a4a;--red:#c0392b;--own:#eaf5ee;--line:#e6e3dc}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121714;--card:#1b221e;--ink:#e8efe9;--muted:#95a39a;--own:#1f3328;--line:#2a332d;--green:#4cc285;--red:#ef6b5b}}}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}}
header{{padding:24px 20px 8px;max-width:1100px;margin:auto}}h1{{margin:0;font-size:22px}}
main{{max-width:1100px;margin:auto;padding:0 20px 40px;display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}h2{{font-size:15px;margin:0 0 2px;display:flex;justify-content:space-between;gap:8px}}
table{{width:100%;border-collapse:collapse;margin-top:6px}}td{{padding:5px 4px;border-top:1px solid var(--line);vertical-align:middle}}
tr.own td{{background:var(--own);font-weight:600}}.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
a{{color:inherit;text-decoration:none}}a:hover{{text-decoration:underline}}.muted{{color:var(--muted);font-weight:400;font-size:13px}}
.up{{color:var(--red)}}.down{{color:var(--green)}}svg{{color:var(--muted);display:block;margin-left:auto}}
.badge{{font-size:12px;padding:2px 8px;border-radius:99px;background:var(--line);white-space:nowrap}}.badge.good{{background:var(--green);color:#fff}}.badge.bad{{background:var(--red);color:#fff}}
.alerts{{grid-column:1/-1}}.alerts ul{{margin:6px 0 0;padding-left:18px}}
</style></head><body><header><h1>Tropik Fiyat Radarı</h1><p class="muted">Son güncelleme: {e(str(s['date']))} · Yeşil satırlar bizim siteler · ▲ zam ▼ indirim (önceki ölçüme göre)</p></header>
<main><section class="card alerts"><h2>Bugünün özeti</h2><ul>{alerts}</ul><p class="muted">Ücretsiz kargo eşikleri — {ship}</p></section>
{''.join(cards)}</main></body></html>"""


def build(send: bool = True) -> dict:
    s = summarize()
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(render_html(s), encoding="utf-8")
    (ROOT / "docs" / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if send:
        send_telegram(telegram_text(s, os.getenv("PANEL_URL", "")))
    return s
