# Tropik Fiyat Radarı

Tropik Hasat / Bizim Tropikal için günlük rakip fiyat takibi.
Bot her sabah 07:17'de rakip sitelerdeki fiyatları çeker, birim fiyata çevirir (₺/kg, ₺/adet), geçmişi saklar, paneli günceller ve Telegram'a kısa bir özet gönderir.

## Kurulum (bir kez, ~10 dk)
1. Bu klasörü yeni bir **GitHub** deposuna yükle. Gizli (private) depo olabilir.
2. **Telegram:** @BotFather ile bot aç → token'ı al. Botu Ercan Abi'nin grubuna ekle → grup chat id'sini al.
3. Depoda: Settings → Secrets → Actions → `TELEGRAM_TOKEN` ve `TELEGRAM_CHAT_ID` ekle.
4. Panel için: Settings → Pages → Branch: `main`, klasör `/docs`. Çıkan linki Settings → Variables'a `PANEL_URL` olarak ekle.
5. Actions → "Günlük fiyat taraması" → **Run workflow** ile ilk taramayı elle başlat.

## Rakip / ürün eklemek
`config/products.yaml` dosyasında ilgili ürünün altına bir satır ekle:
```yaml
- {site: Yeni Rakip, qty: 1, url: "https://..."}
```
`qty`: linkteki paketin miktarıdır (250 g ise `0.25`, 10'lu paket ise `10`). Sayfada seçenek varsa `variant: "1 kg"` yazılır.

## Yerelde çalıştırma
```
pip install -r requirements.txt
python run.py            # tara + rapor + Telegram
python run.py --rapor    # sadece rapor
python -m pytest tests   # testler
```

## Notlar
- `robots.txt` dosyası izin vermeyen sitelere girilmez. Örneğin avoda.market bu yüzden listede yok.
- Her istek arasında 1,5–3,5 sn beklenir; siteler yorulmaz.
- Tükenmiş ürünler "en ucuz rakip" hesabına katılmaz.
- Fiyatı okunamayan link panelde gri yazıyla görünür. O site için `products.yaml` içindeki linki ya da `variant` alanını kontrol et.
- Veriler `data/prices.csv` dosyasında. Excel'de açılabilir.
