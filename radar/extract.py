"""Bir ürün sayfasının HTML'inden fiyat çıkarır.

Sırayla denenir:
  1. WooCommerce varyasyon verisi (URL'de attribute_pa_... varsa)
  2. JSON-LD (schema.org Product / Offer / AggregateOffer)
  3. Next.js / gömülü JSON (__NEXT_DATA__ vb.) içinde varyant arama
  4. Meta etiketleri (product:price:amount, itemprop=price)
  5. Fiyat sınıflı HTML öğelerinde "₺ / TL" metni
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


@dataclass
class PriceResult:
    price: float | None
    in_stock: bool | None
    method: str
    note: str = ""


# ---------- yardımcılar ----------

def parse_price(value) -> float | None:
    """'1.234,56 ₺', '1234.56', '400.00', 1234 -> float"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = str(value)
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        # hangisi sonda ise ondalık ayırıcı odur
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = (head.replace(",", "") + "." + tail) if len(tail) <= 2 else s.replace(",", "")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _norm(text: str) -> str:
    text = (text or "").replace("İ", "i").replace("I", "ı").lower()
    return text.replace("ı", "i")


def variant_matches(text: str, variant: str | None) -> bool:
    if not variant:
        return True
    pattern = r"(?<![\d.,])" + r"\s*".join(re.escape(p) for p in _norm(variant).split())
    if re.match(r".*\d$", _norm(variant)):
        pattern += r"(?![\d])"
    return re.search(pattern, _norm(text)) is not None


def _availability(value) -> bool | None:
    if value is None:
        return None
    v = str(value).lower()
    if "outofstock" in v or "soldout" in v:
        return False
    if "instock" in v or "limitedavailability" in v or "preorder" in v:
        return True
    return None


# ---------- 1. WooCommerce ----------

def _from_woocommerce(soup: BeautifulSoup, url: str) -> PriceResult | None:
    attrs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items() if k.startswith("attribute_")}
    form = soup.find("form", attrs={"data-product_variations": True})
    if not attrs or not form:
        return None
    try:
        variations = json.loads(form["data-product_variations"])
    except (ValueError, TypeError):
        return None
    for var in variations or []:
        va = var.get("attributes", {})
        if all(_norm(va.get(k, "")) in ("", _norm(v)) for k, v in attrs.items()):
            return PriceResult(parse_price(var.get("display_price")), var.get("is_in_stock"), "woocommerce")
    return None


# ---------- 2. JSON-LD ----------

def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _types(node) -> set[str]:
    t = node.get("@type", [])
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _from_jsonld(soup: BeautifulSoup, variant: str | None) -> PriceResult | None:
    offers: list[tuple[str, dict]] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        for node in _walk(data):
            if "product" in _types(node) or "productgroup" in _types(node):
                pname = node.get("name", "")
                raw = node.get("offers")
                for off in _walk(raw):
                    if "offer" in _types(off) and ("price" in off or "lowPrice" in off):
                        label = " ".join(str(off.get(k, "")) for k in ("name", "sku", "description"))
                        offers.append((label or pname, off, pname))
                for var in node.get("hasVariant", []) or []:
                    for off in _walk(var.get("offers")):
                        if "price" in off:
                            offers.append((str(var.get("name", "")), off, pname))
    if not offers:
        return None
    if len(offers) == 1:
        label, off, _ = offers[0]
        return PriceResult(parse_price(off.get("price") or off.get("lowPrice")), _availability(off.get("availability")), "jsonld")
    for label, off, pname in offers:
        if variant_matches(label, variant):
            return PriceResult(parse_price(off.get("price")), _availability(off.get("availability")), "jsonld-variant")
    if not variant:
        label, off, _ = offers[0]
        return PriceResult(parse_price(off.get("price") or off.get("lowPrice")), _availability(off.get("availability")), "jsonld-first")
    return None


# ---------- 3. Gömülü JSON (Next.js vb.) ----------

_LABEL_KEYS = ("title", "name", "option1", "optionValue", "label", "value", "variantName", "displayName")
_PRICE_KEYS = ("price", "salePrice", "sellPrice", "finalPrice", "discountedPrice")


def _from_embedded_json(soup: BeautifulSoup, variant: str | None) -> PriceResult | None:
    if not variant:
        return None
    for tag in soup.find_all("script"):
        txt = tag.string or ""
        if tag.get("id") != "__NEXT_DATA__" and tag.get("type") != "application/json":
            continue
        try:
            data = json.loads(txt)
        except ValueError:
            continue
        for node in _walk(data):
            price_key = next((k for k in _PRICE_KEYS if k in node), None)
            if not price_key:
                continue
            label = " ".join(str(node.get(k, "")) for k in _LABEL_KEYS if isinstance(node.get(k), (str, int, float)))
            if label and variant_matches(label, variant):
                price = node[price_key]
                if isinstance(price, dict):
                    price = price.get("amount") or price.get("value")
                p = parse_price(price)
                if p:
                    stock = node.get("available", node.get("inStock"))
                    return PriceResult(p, stock if isinstance(stock, bool) else None, "embedded-json")
    return None


# ---------- 4. Meta ----------

def _from_meta(soup: BeautifulSoup) -> PriceResult | None:
    for sel in ('meta[property="product:price:amount"]', 'meta[property="og:price:amount"]',
                '[itemprop="price"][content]', 'meta[name="twitter:data1"]'):
        el = soup.select_one(sel)
        if el and parse_price(el.get("content")):
            avail = soup.select_one('[itemprop="availability"]')
            return PriceResult(parse_price(el.get("content")),
                               _availability(avail.get("href") or avail.get("content")) if avail else None, "meta")
    return None


# ---------- 5. HTML metni ----------

_PRICE_RE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:₺|TL)", re.I)
_PRICE_RE2 = re.compile(r"₺\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)")


def _from_html(soup: BeautifulSoup) -> PriceResult | None:
    candidates = soup.select('[class*="price" i] ins, [class*="price" i], [id*="price" i]')
    for el in candidates:
        text = el.get_text(" ", strip=True)
        m = _PRICE_RE.search(text) or _PRICE_RE2.search(text)
        if m:
            p = parse_price(m.group(1))
            if p:
                page = _norm(soup.get_text(" ", strip=True))
                stock = False if ("tükendi" in page or "stokta yok" in page) else None
                return PriceResult(p, stock, "html")
    return None


def extract_price(html: str, url: str, variant: str | None = None) -> PriceResult:
    soup = BeautifulSoup(html, "html.parser")
    for fn in (lambda: _from_woocommerce(soup, url),
               lambda: _from_jsonld(soup, variant),
               lambda: _from_embedded_json(soup, variant),
               lambda: None if variant else _from_meta(soup),
               lambda: None if variant else _from_html(soup)):
        res = fn()
        if res and res.price:
            return res
    return PriceResult(None, None, "none", "fiyat bulunamadı")
