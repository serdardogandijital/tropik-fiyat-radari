"""Takip listesindeki tüm linkleri gezer, fiyatları data/prices.csv'ye ekler."""
from __future__ import annotations

import csv
import datetime as dt
import random
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests
import yaml

from .extract import extract_price

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "products.yaml"
PRICES = ROOT / "data" / "prices.csv"
FIELDS = ["date", "product_key", "product_name", "unit", "site", "own", "url",
          "price", "qty", "unit_price", "in_stock", "method", "status"]

UA = "TropikFiyatRadari/1.0 (+gunluk fiyat takibi; iletisim: tropikhasat.com)"
HEADERS = {"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"}

_robots: dict[str, robotparser.RobotFileParser | None] = {}


def allowed(url: str, session: requests.Session) -> bool:
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = session.get(host + "/robots.txt", timeout=15)
            rp.parse(r.text.splitlines() if r.ok else [])
        except requests.RequestException:
            rp.parse([])
        _robots[host] = rp
    return _robots[host].can_fetch(UA, url)


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def scrape(today: str | None = None) -> list[dict]:
    today = today or dt.date.today().isoformat()
    cfg = load_config()
    session = requests.Session()
    session.headers.update(HEADERS)
    page_cache: dict[str, str | Exception] = {}
    rows: list[dict] = []

    for prod in cfg["products"]:
        for off in prod["offers"]:
            url = off["url"]
            row = {"date": today, "product_key": prod["key"], "product_name": prod["name"],
                   "unit": prod["unit"], "site": off["site"], "own": bool(off.get("own")),
                   "url": url, "qty": off.get("qty", 1), "price": "", "unit_price": "",
                   "in_stock": "", "method": "", "status": "ok"}
            try:
                if not allowed(url, session):
                    row["status"] = "robots.txt izin vermiyor"
                    rows.append(row)
                    continue
                if url not in page_cache:
                    time.sleep(random.uniform(1.5, 3.5))  # siteleri yormamak için
                    resp = session.get(url, timeout=30)
                    resp.raise_for_status()
                    page_cache[url] = resp.text
                res = extract_price(page_cache[url], url, off.get("variant"))
                row["method"] = res.method
                if res.price:
                    row["price"] = round(res.price, 2)
                    row["unit_price"] = round(res.price / float(row["qty"]), 2)
                    row["in_stock"] = "" if res.in_stock is None else res.in_stock
                else:
                    row["status"] = res.note or "fiyat bulunamadı"
            except requests.HTTPError as e:
                row["status"] = f"HTTP {e.response.status_code}"
            except requests.RequestException as e:
                row["status"] = f"bağlantı hatası: {type(e).__name__}"
            rows.append(row)
            print(f"{row['site']:<22} {prod['key']:<18} {row['price'] or '-':>9}  {row['status']}")
    return rows


def save(rows: list[dict]) -> None:
    PRICES.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if PRICES.exists():
        with PRICES.open(encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    days = {r["date"] for r in rows}
    existing = [r for r in existing if r["date"] not in days]  # aynı gün 2. çalıştırma üzerine yazar
    with PRICES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(existing + rows)
