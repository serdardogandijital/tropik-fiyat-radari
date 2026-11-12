"""Günlük çalıştırma: python run.py  (sadece rapor için: python run.py --rapor)"""
import sys
from radar.scrape import scrape, save
from radar.report import build

if __name__ == "__main__":
    if "--rapor" not in sys.argv:
        save(scrape())
    build(send="--sessiz" not in sys.argv)
